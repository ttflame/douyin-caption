import difflib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.identity.models import Member
from app.modules.identity.router import get_current_member
from app.modules.tasks.ai_lock import (
    IN_MEMORY_MEMBER_AI_CALL_LOCK,
    AiLockUnavailableError,
    InMemoryMemberAiCallLock,
    MemberAiCallBusyError,
    MemberAiCallLock,
)
from app.modules.tasks.ai_operations import TaskAiExecutionError, TaskAiOperationService
from app.modules.tasks.ai_queue import ACTIVE_STATUSES, AiQueueService
from app.modules.tasks.domain import (
    AiOperationKind,
    LockConstraint,
    TaskState,
    ValidationStatus,
    VersionKind,
    validate_lock_constraints,
)
from app.modules.tasks.models import (
    AiOperation,
    AnalysisRecord,
    LockedFragment,
    RewriteTask,
    ScriptVersion,
    SuggestionRecord,
)
from app.modules.tasks.repository import (
    PresetNotFoundError,
    PresetRepository,
    TaskNotFoundError,
    TaskRepository,
)
from app.modules.tasks.schemas import (
    AiOperationView,
    AnalysisCorrection,
    AnalysisSubmit,
    AnalysisView,
    FirstDraftSubmit,
    LockedFragmentCreate,
    LockedFragmentView,
    ManualEditCreate,
    PresetCreate,
    PresetUpdate,
    PresetView,
    RevisionSubmit,
    SuggestionsSubmit,
    SuggestionUpdate,
    SuggestionView,
    TaskCreate,
    TaskDetail,
    TaskSummary,
    TaskUpdate,
    VersionView,
)
from app.modules.tasks.service import (
    TaskDomainService,
    TaskSnapshot,
    assert_no_overlapping_range,
    selected_text,
)

router = APIRouter()


async def _commit_and_refresh(session: AsyncSession, instance: object) -> None:
    await session.commit()
    await session.refresh(instance)


class TaskApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def task_exception_handler(_: Request, exc: TaskApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


class VersionCompareRequest(BaseModel):
    left_version_id: UUID
    right_version_id: UUID


class VersionCompareResponse(BaseModel):
    left_version_id: UUID
    right_version_id: UUID
    diff: str


def _task_not_found() -> TaskApiError:
    return TaskApiError("task_not_found", "Task was not found", 404)


def _preset_not_found() -> TaskApiError:
    return TaskApiError("preset_not_found", "Preset was not found", 404)


def _version_not_found() -> TaskApiError:
    return TaskApiError("version_not_found", "Version was not found", 404)


async def _owned_task(session: AsyncSession, task_id: UUID, owner_id: UUID) -> RewriteTask:
    try:
        return await TaskRepository(session).get_owned(task_id, owner_id)
    except TaskNotFoundError as exc:
        raise _task_not_found() from exc


async def _owned_version(
    session: AsyncSession, task_id: UUID, version_id: UUID, owner_id: UUID
) -> ScriptVersion:
    statement = (
        select(ScriptVersion)
        .join(RewriteTask, RewriteTask.id == ScriptVersion.task_id)
        .where(
            ScriptVersion.id == version_id,
            ScriptVersion.task_id == task_id,
            RewriteTask.owner_id == owner_id,
        )
    )
    version = await session.scalar(statement)
    if version is None:
        raise _version_not_found()
    return version


async def _assert_no_active_ai(session: AsyncSession, task_id: UUID) -> None:
    await session.scalar(select(RewriteTask.id).where(RewriteTask.id == task_id).with_for_update())
    active = await session.scalar(
        select(func.count())
        .select_from(AiOperation)
        .where(
            AiOperation.task_id == task_id,
            AiOperation.status.in_(ACTIVE_STATUSES),
        )
    )
    if active:
        raise TaskApiError(
            "ai_operation_in_progress",
            "该文案有排队或执行中的任务，暂时无法修改",
            409,
        )


async def get_member_ai_call_lock() -> AsyncIterator[MemberAiCallLock | InMemoryMemberAiCallLock]:
    settings = get_settings()
    allow_in_memory = bool(getattr(settings, "allow_in_memory_coordination", False))
    if settings.app_env.casefold() != "production" and allow_in_memory:
        yield IN_MEMORY_MEMBER_AI_CALL_LOCK
        return
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield MemberAiCallLock(client)
    finally:
        await client.aclose()


def get_task_ai_operation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    call_lock: Annotated[
        MemberAiCallLock | InMemoryMemberAiCallLock,
        Depends(get_member_ai_call_lock),
    ],
) -> TaskAiOperationService:
    return TaskAiOperationService(session, call_lock)


async def _execute_ai(operation) -> AiOperation:
    try:
        return await operation
    except MemberAiCallBusyError as exc:
        raise TaskApiError(
            "ai_call_in_progress",
            "This member already has an AI call in progress",
            409,
        ) from exc
    except AiLockUnavailableError as exc:
        raise TaskApiError(
            "ai_lock_unavailable",
            "AI calls are temporarily unavailable because concurrency control cannot be verified",
            503,
        ) from exc
    except TaskAiExecutionError as exc:
        raise TaskApiError(
            exc.code,
            exc.message,
            exc.status_code,
            details=exc.details,
        ) from exc


@router.get("/presets", response_model=list[PresetView], tags=["presets"])
async def list_presets(
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await PresetRepository(session).list_owned(member.id)


@router.post("/presets", response_model=PresetView, tags=["presets"])
async def create_preset(
    payload: PresetCreate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        preset = await PresetRepository(session).create(member.id, payload)
        await _commit_and_refresh(session, preset)
    except IntegrityError as exc:
        await session.rollback()
        raise TaskApiError("preset_name_exists", "已有同名预设", 409) from exc
    return preset


@router.patch("/presets/{preset_id}", response_model=PresetView, tags=["presets"])
async def update_preset(
    preset_id: UUID,
    payload: PresetUpdate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    repository = PresetRepository(session)
    try:
        preset = await repository.get_owned(preset_id, member.id)
    except PresetNotFoundError as exc:
        raise _preset_not_found() from exc
    try:
        preset = await repository.replace_settings(
            preset, name=payload.name, settings=payload.settings
        )
        await _commit_and_refresh(session, preset)
    except IntegrityError as exc:
        await session.rollback()
        raise TaskApiError("preset_name_exists", "已有同名预设", 409) from exc
    return preset


@router.delete("/presets/{preset_id}", status_code=204, tags=["presets"])
async def delete_preset(
    preset_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    repository = PresetRepository(session)
    try:
        preset = await repository.get_owned(preset_id, member.id)
    except PresetNotFoundError as exc:
        raise _preset_not_found() from exc
    await repository.delete(preset)
    await session.commit()
    return Response(status_code=204)


@router.get("/tasks", response_model=list[TaskSummary], tags=["tasks"])
async def list_tasks(
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    search: str | None = None,
    state: TaskState | None = None,
    archived: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return await TaskRepository(session).list_owned(
        member.id,
        search=search,
        state=state,
        archived=archived,
        offset=offset,
        limit=limit,
    )


@router.post("/tasks", response_model=TaskDetail, tags=["tasks"])
async def create_task(
    payload: TaskCreate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    task = await TaskRepository(session).create(member.id, payload)
    await _commit_and_refresh(session, task)
    return task


@router.get("/tasks/{task_id}", response_model=TaskDetail, tags=["tasks"])
async def get_task(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await _owned_task(session, task_id, member.id)


@router.patch("/tasks/{task_id}", response_model=TaskDetail, tags=["tasks"])
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    repository = TaskRepository(session)
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    try:
        task = await repository.update_draft(task, payload)
    except ValueError as exc:
        raise TaskApiError("task_not_editable", str(exc), 409) from exc
    await _commit_and_refresh(session, task)
    return task


@router.post("/tasks/{task_id}/copy", response_model=TaskDetail, tags=["tasks"])
async def copy_task(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    repository = TaskRepository(session)
    source = await _owned_task(session, task_id, member.id)
    copied = await repository.copy(source, member.id)
    await _commit_and_refresh(session, copied)
    return copied


@router.post("/tasks/{task_id}/archive", response_model=TaskDetail, tags=["tasks"])
async def archive_task(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    snapshot = TaskSnapshot(
        id=task.id,
        owner_id=task.owner_id,
        state=TaskState(task.state),
        archived_from_state=(
            TaskState(task.archived_from_state) if task.archived_from_state else None
        ),
    )
    TaskDomainService().archive(snapshot)
    task.state = snapshot.state
    task.archived_from_state = snapshot.archived_from_state
    await _commit_and_refresh(session, task)
    return task


@router.post("/tasks/{task_id}/restore", response_model=TaskDetail, tags=["tasks"])
async def restore_task(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    snapshot = TaskSnapshot(
        id=task.id,
        owner_id=task.owner_id,
        state=TaskState(task.state),
        archived_from_state=(
            TaskState(task.archived_from_state) if task.archived_from_state else None
        ),
    )
    try:
        TaskDomainService().restore(snapshot)
    except ValueError as exc:
        raise TaskApiError("task_not_restorable", str(exc), 409) from exc
    task.state = snapshot.state
    task.archived_from_state = snapshot.archived_from_state
    await _commit_and_refresh(session, task)
    return task


@router.post(
    "/tasks/{task_id}/analysis",
    status_code=202,
    response_model=AiOperationView,
    tags=["ai-workflow"],
)
async def submit_analysis(
    task_id: UUID,
    payload: AnalysisSubmit,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    task = await _owned_task(session, task_id, member.id)
    return await _execute_ai(
        AiQueueService(session).submit(
            task, member.id, AiOperationKind.ANALYSIS, payload, idempotency_key
        )
    )


@router.patch(
    "/tasks/{task_id}/analysis/{analysis_id}",
    response_model=AnalysisView,
    tags=["ai-workflow"],
)
async def update_analysis(
    task_id: UUID,
    analysis_id: UUID,
    payload: AnalysisCorrection,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    record = await session.scalar(
        select(AnalysisRecord).where(
            AnalysisRecord.id == analysis_id,
            AnalysisRecord.task_id == task_id,
        )
    )
    if record is None:
        raise TaskApiError("analysis_not_found", "Analysis was not found", 404)
    record.payload = payload.analysis.model_dump(mode="json")
    record.member_notes = payload.member_notes
    await _commit_and_refresh(session, record)
    return record


@router.get(
    "/tasks/{task_id}/analysis/{analysis_id}",
    response_model=AnalysisView,
    tags=["ai-workflow"],
)
async def get_analysis(
    task_id: UUID,
    analysis_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    record = await session.scalar(
        select(AnalysisRecord).where(
            AnalysisRecord.id == analysis_id,
            AnalysisRecord.task_id == task_id,
        )
    )
    if record is None:
        raise TaskApiError("analysis_not_found", "Analysis was not found", 404)
    return record


@router.get(
    "/tasks/{task_id}/analyses",
    response_model=list[AnalysisView],
    tags=["ai-workflow"],
)
async def get_analyses(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    return (
        await session.scalars(
            select(AnalysisRecord)
            .where(AnalysisRecord.task_id == task_id)
            .order_by(AnalysisRecord.sequence)
        )
    ).all()


@router.post(
    "/tasks/{task_id}/suggestions",
    status_code=202,
    response_model=AiOperationView,
    tags=["ai-workflow"],
)
async def submit_suggestions(
    task_id: UUID,
    payload: SuggestionsSubmit,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    task = await _owned_task(session, task_id, member.id)
    return await _execute_ai(
        AiQueueService(session).submit(
            task, member.id, AiOperationKind.SUGGESTIONS, payload, idempotency_key
        )
    )


@router.patch(
    "/tasks/{task_id}/suggestions/{suggestion_id}",
    response_model=SuggestionView,
    tags=["ai-workflow"],
)
async def update_suggestion(
    task_id: UUID,
    suggestion_id: UUID,
    payload: SuggestionUpdate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    record = await session.scalar(
        select(SuggestionRecord).where(
            SuggestionRecord.id == suggestion_id,
            SuggestionRecord.task_id == task_id,
        )
    )
    if record is None:
        raise TaskApiError("suggestion_not_found", "Suggestion was not found", 404)
    record.decision = payload.decision
    record.member_note = payload.member_note
    await _commit_and_refresh(session, record)
    return record


@router.get(
    "/tasks/{task_id}/suggestions",
    response_model=list[SuggestionView],
    tags=["ai-workflow"],
)
async def get_suggestions(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    analysis_id: UUID | None = None,
):
    await _owned_task(session, task_id, member.id)
    selected_analysis_id = analysis_id
    if selected_analysis_id is None:
        selected_analysis_id = await session.scalar(
            select(AnalysisRecord.id).where(
                AnalysisRecord.task_id == task_id,
                AnalysisRecord.is_selected.is_(True),
            )
        )
    if selected_analysis_id is None:
        return []
    return (
        await session.scalars(
            select(SuggestionRecord)
            .where(
                SuggestionRecord.task_id == task_id,
                SuggestionRecord.analysis_id == selected_analysis_id,
            )
            .order_by(SuggestionRecord.created_at)
        )
    ).all()


@router.post(
    "/tasks/{task_id}/first-draft",
    status_code=202,
    response_model=AiOperationView,
    tags=["ai-workflow"],
)
async def submit_first_draft(
    task_id: UUID,
    payload: FirstDraftSubmit,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    task = await _owned_task(session, task_id, member.id)
    return await _execute_ai(
        AiQueueService(session).submit(
            task, member.id, AiOperationKind.FIRST_DRAFT, payload, idempotency_key
        )
    )


@router.post(
    "/tasks/{task_id}/revisions",
    status_code=202,
    response_model=AiOperationView,
    tags=["ai-workflow"],
)
async def submit_revision(
    task_id: UUID,
    payload: RevisionSubmit,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    task = await _owned_task(session, task_id, member.id)
    return await _execute_ai(
        AiQueueService(session).submit(
            task, member.id, AiOperationKind.REVISION, payload, idempotency_key
        )
    )


@router.get("/operations", response_model=list[AiOperationView], tags=["ai-workflow"])
async def list_ai_operations(
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await AiQueueService(session).list_owned(member.id)


@router.delete("/operations/history", status_code=204, tags=["ai-workflow"])
async def clear_ai_operation_history(
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await AiQueueService(session).clear_completed(member.id)
    return Response(status_code=204)


@router.post(
    "/operations/{operation_id}/cancel", response_model=AiOperationView, tags=["ai-workflow"]
)
async def cancel_ai_operation(
    operation_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await _execute_ai(AiQueueService(session).cancel(member.id, operation_id))


@router.post(
    "/operations/{operation_id}/retry",
    status_code=202,
    response_model=AiOperationView,
    tags=["ai-workflow"],
)
async def retry_ai_operation(
    operation_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
):
    return await _execute_ai(
        AiQueueService(session).retry(member.id, operation_id, idempotency_key)
    )


@router.get("/operations/{operation_id}", response_model=AiOperationView, tags=["ai-workflow"])
async def get_ai_operation(
    operation_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    operations: Annotated[TaskAiOperationService, Depends(get_task_ai_operation_service)],
):
    try:
        return await operations.get_owned_operation(operation_id, member.id)
    except TaskAiExecutionError as exc:
        raise TaskApiError(exc.code, exc.message, exc.status_code, details=exc.details) from exc


@router.get("/tasks/{task_id}/versions", response_model=list[VersionView], tags=["versions"])
async def list_versions(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    statement = (
        select(ScriptVersion)
        .where(ScriptVersion.task_id == task_id)
        .order_by(ScriptVersion.created_at)
    )
    return (await session.scalars(statement)).all()


@router.get("/tasks/{task_id}/versions/{version_id}", response_model=VersionView, tags=["versions"])
async def get_version(
    task_id: UUID,
    version_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await _owned_version(session, task_id, version_id, member.id)


@router.post(
    "/tasks/{task_id}/versions/{version_id}/manual-edit",
    response_model=VersionView,
    tags=["versions"],
)
async def create_manual_edit(
    task_id: UUID,
    version_id: UUID,
    payload: ManualEditCreate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    parent = await _owned_version(session, task_id, version_id, member.id)
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    if task.state == TaskState.ARCHIVED:
        raise TaskApiError("task_archived", "An archived task cannot be edited", 409)
    if not await TaskRepository(session).has_first_draft(task_id):
        raise TaskApiError("first_draft_required", "A manual edit requires a first draft", 409)
    locks = list(
        (
            await session.scalars(select(LockedFragment).where(LockedFragment.task_id == task_id))
        ).all()
    )
    if validate_lock_constraints(
        payload.content,
        [LockConstraint(text=item.text, order_index=item.order_index) for item in locks],
    ):
        raise TaskApiError("locked_text_changed", "编辑内容改动了保留句，请先取消对应锁定。", 409)
    version = ScriptVersion(
        task_id=task_id,
        parent_id=parent.id,
        kind=VersionKind.MANUAL_EDIT,
        content=payload.content,
        instruction=payload.instruction,
        provenance={"source": "member_manual_edit"},
        validation_status=ValidationStatus.NOT_CHECKED,
        validation_details={},
        is_current_final=False,
    )
    session.add(version)
    task.state = TaskState.EDITING
    await session.commit()
    await session.refresh(version)
    return version


@router.post(
    "/tasks/{task_id}/versions/compare",
    response_model=VersionCompareResponse,
    tags=["versions"],
)
async def compare_versions(
    task_id: UUID,
    payload: VersionCompareRequest,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    left = await _owned_version(session, task_id, payload.left_version_id, member.id)
    right = await _owned_version(session, task_id, payload.right_version_id, member.id)
    diff = "".join(
        difflib.unified_diff(
            left.content.splitlines(keepends=True),
            right.content.splitlines(keepends=True),
            fromfile=str(left.id),
            tofile=str(right.id),
        )
    )
    return VersionCompareResponse(
        left_version_id=left.id,
        right_version_id=right.id,
        diff=diff,
    )


@router.post(
    "/tasks/{task_id}/versions/{version_id}/locks",
    response_model=LockedFragmentView,
    tags=["versions"],
)
async def create_lock(
    task_id: UUID,
    version_id: UUID,
    payload: LockedFragmentCreate,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    version = await _owned_version(session, task_id, version_id, member.id)
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    if task.state == TaskState.ARCHIVED:
        raise TaskApiError("task_archived", "An archived task cannot be changed", 409)
    try:
        text = selected_text(version.content, payload.start_offset, payload.end_offset)
    except ValueError as exc:
        raise TaskApiError("invalid_selection", str(exc), 400) from exc
    ranges = (
        await session.execute(
            select(LockedFragment.start_offset, LockedFragment.end_offset).where(
                LockedFragment.task_id == task_id,
                LockedFragment.source_version_id == version_id,
            )
        )
    ).all()
    try:
        assert_no_overlapping_range(payload.start_offset, payload.end_offset, list(ranges))
    except ValueError as exc:
        raise TaskApiError("lock_overlap", str(exc), 409) from exc
    next_order = await session.scalar(
        select(func.coalesce(func.max(LockedFragment.order_index), -1) + 1).where(
            LockedFragment.task_id == task_id
        )
    )
    lock = LockedFragment(
        task_id=task_id,
        source_version_id=version_id,
        text=text,
        start_offset=payload.start_offset,
        end_offset=payload.end_offset,
        order_index=next_order,
        note=payload.note,
    )
    session.add(lock)
    await session.commit()
    await session.refresh(lock)
    return lock


@router.delete("/tasks/{task_id}/locks/{lock_id}", status_code=204, tags=["versions"])
async def delete_lock(
    task_id: UUID,
    lock_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    result = await session.execute(
        delete(LockedFragment).where(
            LockedFragment.id == lock_id,
            LockedFragment.task_id == task_id,
        )
    )
    if result.rowcount == 0:
        raise TaskApiError("lock_not_found", "Locked fragment was not found", 404)
    await session.commit()
    return Response(status_code=204)


@router.get("/tasks/{task_id}/locks", response_model=list[LockedFragmentView], tags=["versions"])
async def get_locks(
    task_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _owned_task(session, task_id, member.id)
    return (
        await session.scalars(
            select(LockedFragment)
            .where(LockedFragment.task_id == task_id)
            .order_by(LockedFragment.order_index)
        )
    ).all()


@router.post(
    "/tasks/{task_id}/versions/{version_id}/finalize",
    response_model=VersionView,
    tags=["versions"],
)
async def finalize_version(
    task_id: UUID,
    version_id: UUID,
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    version = await _owned_version(session, task_id, version_id, member.id)
    task = await _owned_task(session, task_id, member.id)
    await _assert_no_active_ai(session, task_id)
    if task.state == TaskState.ARCHIVED:
        raise TaskApiError("task_archived", "An archived task cannot be finalized", 409)
    await session.execute(
        update(ScriptVersion).where(ScriptVersion.task_id == task_id).values(is_current_final=False)
    )
    version.is_current_final = True
    task.state = TaskState.FINALIZED
    task.finalized_at = datetime.now(UTC)
    await _commit_and_refresh(session, version)
    return version


@router.get("/tasks/{task_id}/export", tags=["versions"])
async def export_final_version(
    task_id: UUID,
    format: Literal["txt", "md"],
    member: Annotated[Member, Depends(get_current_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    await _owned_task(session, task_id, member.id)
    version = await session.scalar(
        select(ScriptVersion).where(
            ScriptVersion.task_id == task_id,
            ScriptVersion.is_current_final.is_(True),
        )
    )
    if version is None:
        raise TaskApiError("final_version_not_found", "Task has no current final version", 404)
    media_type = "text/plain; charset=utf-8" if format == "txt" else "text/markdown; charset=utf-8"
    return Response(
        content=version.content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{task_id}.{format}"'},
    )
