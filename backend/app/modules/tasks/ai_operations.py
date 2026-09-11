"""Persistence orchestration for task AI operations."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, TypeVar
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_limits import AI_OPERATION_STALE_SECONDS
from app.core.config import get_settings
from app.core.provider_url import ProviderUrlPolicy, ProviderUrlPolicyError
from app.modules.ai.dto import (
    AnalysisResult,
    SelectedSuggestion,
    Selection,
    Suggestion,
    SuggestionSet,
)
from app.modules.ai.provider import ProviderConfig
from app.modules.identity.models import ProviderSetting
from app.modules.identity.security import ApiKeyCipher, InvalidEncryptedValueError
from app.modules.tasks.ai_lock import MemberAiCallLock
from app.modules.tasks.ai_service import (
    AiOperationFailed,
    AnalysisServiceResult,
    LockedFragmentSnapshot,
    SuggestionsServiceResult,
    TaskAiService,
    TaskAiSnapshot,
    VersionAiSnapshot,
    VersionServiceResult,
)
from app.modules.tasks.domain import (
    AiOperationKind,
    AiOperationStatus,
    SuggestionDecision,
    TaskState,
    assert_transition,
)
from app.modules.tasks.models import (
    AiOperation,
    AnalysisRecord,
    LockedFragment,
    RewriteTask,
    ScriptVersion,
    SuggestionRecord,
)
from app.modules.tasks.schemas import (
    AnalysisSubmit,
    CreativeSettings,
    FirstDraftSubmit,
    RevisionSubmit,
    SuggestionsSubmit,
)


class TaskAiExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


ServiceResult = TypeVar(
    "ServiceResult", AnalysisServiceResult, SuggestionsServiceResult, VersionServiceResult
)
PersistResult = Callable[[ServiceResult], Awaitable[tuple[str, UUID]]]
STALE_OPERATION_AFTER = timedelta(seconds=AI_OPERATION_STALE_SECONDS)


class TaskAiOperationService:
    def __init__(
        self,
        session: AsyncSession,
        call_lock: MemberAiCallLock,
        *,
        ai_service: TaskAiService | None = None,
        cipher: ApiKeyCipher | None = None,
        provider_url_policy: ProviderUrlPolicy | None = None,
        queued_operation_id: UUID | None = None,
    ) -> None:
        self._session = session
        self._call_lock = call_lock
        self._queued_operation_id = queued_operation_id
        self._ai = ai_service or TaskAiService()
        self._cipher = cipher or ApiKeyCipher(get_settings().key_encryption_secret)
        self._provider_url_policy = provider_url_policy or ProviderUrlPolicy(
            production=get_settings().app_env == "production"
        )

    async def analyze(
        self,
        task: RewriteTask,
        owner_id: UUID,
        payload: AnalysisSubmit,
        idempotency_key: str | None,
    ) -> AiOperation:
        await self.recover_stale_operations(owner_id)
        has_first_draft = await self._has_first_draft(task.id)
        request_hash = _request_hash(
            AiOperationKind.ANALYSIS,
            task.id,
            {
                "source_text": task.source_text,
                "creative_settings": task.creative_settings,
                "payload": payload.model_dump(mode="json"),
            },
        )

        async def invoke(
            config: ProviderConfig, model: str, initial_state: TaskState
        ) -> AnalysisServiceResult:
            return await self._ai.analyze(
                _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                config,
                model,
            )

        async def persist(result: AnalysisServiceResult) -> tuple[str, UUID]:
            await self._session.execute(
                update(AnalysisRecord)
                .where(AnalysisRecord.task_id == task.id)
                .values(is_selected=False)
            )
            sequence = await self._session.scalar(
                select(func.coalesce(func.max(AnalysisRecord.sequence), 0) + 1).where(
                    AnalysisRecord.task_id == task.id
                )
            )
            record = AnalysisRecord(
                task_id=task.id,
                sequence=sequence,
                payload=result.analysis.model_dump(mode="json"),
                member_notes=None,
                is_selected=True,
                prompt_template_version=result.metadata.prompt_template_version,
                model_identifier=result.metadata.model_identifier,
            )
            self._session.add(record)
            await self._session.flush()
            return "analysis", record.id

        return await self._execute(
            task,
            owner_id,
            AiOperationKind.ANALYSIS,
            idempotency_key,
            request_hash,
            invoke,
            persist,
        )

    async def suggest(
        self,
        task: RewriteTask,
        owner_id: UUID,
        payload: SuggestionsSubmit,
        idempotency_key: str | None,
    ) -> AiOperation:
        await self.recover_stale_operations(owner_id)
        analysis_record = await self._analysis(task.id, payload.analysis_id)
        analysis = _stored_analysis(analysis_record)
        has_first_draft = await self._has_first_draft(task.id)
        previous = list(
            (
                await self._session.scalars(
                    select(SuggestionRecord)
                    .where(
                        SuggestionRecord.task_id == task.id,
                        SuggestionRecord.analysis_id == analysis_record.id,
                    )
                    .order_by(SuggestionRecord.created_at, SuggestionRecord.id)
                )
            ).all()
        )
        fixed = [item for item in previous if item.decision == SuggestionDecision.ACCEPTED]
        if previous and len(fixed) == len(previous):
            raise TaskAiExecutionError(
                "all_suggestions_fixed", "所有方案均已固定，请先取消勾选需要优化的方案", 409
            )
        request_hash = _request_hash(
            AiOperationKind.SUGGESTIONS,
            task.id,
            {
                "analysis": analysis_record.payload,
                "payload": payload.model_dump(mode="json"),
            },
        )

        async def invoke(
            config: ProviderConfig, model: str, initial_state: TaskState
        ) -> SuggestionsServiceResult:
            return await self._ai.suggest(
                _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                analysis,
                config,
                model,
                member_context=payload.member_context,
                previous_suggestions=[_stored_suggestion(item) for item in previous],
                fixed_suggestions=[
                    SelectedSuggestion(
                        suggestion=_stored_suggestion(item), note=item.member_note or ""
                    )
                    for item in fixed
                ],
            )

        async def persist(result: SuggestionsServiceResult) -> tuple[str, UUID]:
            fixed_keys = {item.suggestion_key for item in fixed}
            fixed_titles = {item.title.strip() for item in fixed}
            replacements = [
                item
                for item in result.suggestions.suggestions
                if item.suggestion_id not in fixed_keys and item.title.strip() not in fixed_titles
            ]
            capacity = (max(5, min(8, len(previous))) if previous else 8) - len(fixed)
            replacements = replacements[:capacity]
            # Validate the combined result before replacing any saved, unselected rows.
            SuggestionSet(suggestions=[_stored_suggestion(item) for item in fixed] + replacements)
            await self._session.execute(
                delete(SuggestionRecord).where(
                    SuggestionRecord.task_id == task.id,
                    SuggestionRecord.analysis_id == analysis_record.id,
                    SuggestionRecord.decision != SuggestionDecision.ACCEPTED,
                )
            )
            records = [
                SuggestionRecord(
                    task_id=task.id,
                    analysis_id=analysis_record.id,
                    suggestion_key=item.suggestion_id,
                    analysis_issue_ids=item.analysis_issue_ids,
                    priority=item.priority,
                    title=item.title,
                    problem=item.problem,
                    direction=item.direction,
                    reason=item.rationale,
                    impact_scope=item.impact_scope,
                    example=item.example,
                    decision=SuggestionDecision.PENDING,
                    member_note=None,
                )
                for item in replacements
            ]
            self._session.add_all(records)
            await self._session.flush()
            return "suggestions", analysis_record.id

        return await self._execute(
            task,
            owner_id,
            AiOperationKind.SUGGESTIONS,
            idempotency_key,
            request_hash,
            invoke,
            persist,
        )

    async def create_first_draft(
        self,
        task: RewriteTask,
        owner_id: UUID,
        payload: FirstDraftSubmit,
        idempotency_key: str | None,
    ) -> AiOperation:
        await self.recover_stale_operations(owner_id)
        analysis_record = await self._analysis(task.id, payload.analysis_id)
        analysis = _stored_analysis(analysis_record)
        suggestion_records = (
            await self._session.scalars(
                select(SuggestionRecord).where(
                    SuggestionRecord.task_id == task.id,
                    SuggestionRecord.analysis_id == analysis_record.id,
                )
            )
        ).all()
        suggestion_set = SuggestionSet(
            suggestions=[_stored_suggestion(item) for item in suggestion_records]
        )
        selected = [
            SelectedSuggestion(suggestion=_stored_suggestion(item), note=item.member_note or "")
            for item in suggestion_records
            if item.decision == SuggestionDecision.ACCEPTED
        ]
        has_first_draft = await self._has_first_draft(task.id)
        request_hash = _request_hash(
            AiOperationKind.FIRST_DRAFT,
            task.id,
            {
                "analysis": analysis_record.payload,
                "suggestions": [
                    {
                        "id": str(item.id),
                        "decision": item.decision,
                        "note": item.member_note,
                    }
                    for item in suggestion_records
                ],
                "payload": payload.model_dump(mode="json"),
            },
        )

        # Re-validation prevents stale or manually corrupted suggestion rows reaching the model.
        del suggestion_set

        async def invoke(
            config: ProviderConfig, model: str, initial_state: TaskState
        ) -> VersionServiceResult:
            return await self._ai.create_first_draft(
                _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                analysis,
                selected,
                config,
                model,
                member_requirements=payload.member_requirements,
            )

        async def persist(result: VersionServiceResult) -> tuple[str, UUID]:
            version = _version_record(task.id, result)
            self._session.add(version)
            await self._session.flush()
            return "version", version.id

        return await self._execute(
            task,
            owner_id,
            AiOperationKind.FIRST_DRAFT,
            idempotency_key,
            request_hash,
            invoke,
            persist,
        )

    async def revise(
        self,
        task: RewriteTask,
        owner_id: UUID,
        payload: RevisionSubmit,
        idempotency_key: str | None,
    ) -> AiOperation:
        await self.recover_stale_operations(owner_id)
        parent = await self._session.scalar(
            select(ScriptVersion).where(
                ScriptVersion.id == payload.parent_version_id,
                ScriptVersion.task_id == task.id,
            )
        )
        if parent is None:
            raise TaskAiExecutionError("version_not_found", "Version was not found", 404)
        locks = (
            await self._session.scalars(
                select(LockedFragment)
                .where(
                    LockedFragment.task_id == task.id,
                )
                .order_by(LockedFragment.order_index)
            )
        ).all()
        lock_snapshots = [
            LockedFragmentSnapshot(id=item.id, text=item.text, order_index=item.order_index)
            for item in locks
        ]
        has_first_draft = await self._has_first_draft(task.id)
        parent_snapshot = VersionAiSnapshot(id=parent.id, content=parent.content)
        analysis_record = None
        analysis = None
        selected: list[SelectedSuggestion] = []
        if payload.scope == "suggestions":
            analysis_record = await self._analysis(task.id, payload.analysis_id)
            analysis = _stored_analysis(analysis_record)
            suggestion_records = list(
                (
                    await self._session.scalars(
                        select(SuggestionRecord).where(
                            SuggestionRecord.task_id == task.id,
                            SuggestionRecord.analysis_id == analysis_record.id,
                        )
                    )
                ).all()
            )
            SuggestionSet(suggestions=[_stored_suggestion(item) for item in suggestion_records])
            selected = [
                SelectedSuggestion(
                    suggestion=_stored_suggestion(item), note=item.member_note or ""
                )
                for item in suggestion_records
                if item.decision == SuggestionDecision.ACCEPTED
            ]
        request_hash = _request_hash(
            AiOperationKind.REVISION,
            task.id,
            {
                "parent_id": str(parent.id),
                "parent_content": parent.content,
                "locks": [
                    {"id": str(item.id), "text": item.text, "order": item.order_index}
                    for item in locks
                ],
                "payload": payload.model_dump(mode="json"),
                "analysis": analysis_record.payload if analysis_record else None,
                "suggestions": [item.model_dump(mode="json") for item in selected],
            },
        )

        async def invoke(
            config: ProviderConfig, model: str, initial_state: TaskState
        ) -> VersionServiceResult:
            if payload.scope == "suggestions":
                assert analysis is not None
                return await self._ai.regenerate_from_suggestions(
                    _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                    parent_snapshot,
                    analysis,
                    selected,
                    payload.instruction,
                    lock_snapshots,
                    config,
                    model,
                )
            if payload.scope == "full":
                return await self._ai.revise_full(
                    _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                    parent_snapshot,
                    payload.instruction,
                    lock_snapshots,
                    config,
                    model,
                )
            return await self._ai.revise_selection(
                _task_snapshot(task, has_first_draft=has_first_draft, state=initial_state),
                parent_snapshot,
                Selection(start=payload.selection_start, end=payload.selection_end),  # type: ignore[arg-type]
                payload.instruction,
                lock_snapshots,
                config,
                model,
            )

        async def persist(result: VersionServiceResult) -> tuple[str, UUID]:
            version = _version_record(task.id, result)
            self._session.add(version)
            await self._session.flush()
            return "version", version.id

        return await self._execute(
            task,
            owner_id,
            AiOperationKind.REVISION,
            idempotency_key,
            request_hash,
            invoke,
            persist,
        )

    async def get_owned_operation(self, operation_id: UUID, owner_id: UUID) -> AiOperation:
        operation = await self._session.scalar(
            select(AiOperation).where(
                AiOperation.id == operation_id,
                AiOperation.owner_id == owner_id,
            )
        )
        if operation is None:
            raise TaskAiExecutionError("operation_not_found", "AI operation was not found", 404)
        return operation

    async def recover_stale_operations(self, owner_id: UUID) -> int:
        cutoff = datetime.now(UTC) - STALE_OPERATION_AFTER
        operations = (
            await self._session.scalars(
                select(AiOperation).where(
                    AiOperation.owner_id == owner_id,
                    AiOperation.status == AiOperationStatus.RUNNING,
                    AiOperation.started_at < cutoff,
                )
            )
        ).all()
        for operation in operations:
            task = await self._session.get(RewriteTask, operation.task_id)
            if task is not None and task.state == operation.running_task_state:
                task.state = operation.initial_task_state
            operation.status = AiOperationStatus.FAILED
            operation.completed_task_state = operation.initial_task_state
            operation.error_code = "ai_operation_stale"
            operation.error_message = "The AI operation did not finish and was recovered"
            operation.error_details = {"retryable": True}
            operation.completed_at = datetime.now(UTC)
        if operations:
            await self._session.commit()
        return len(operations)

    async def _execute(
        self,
        task: RewriteTask,
        owner_id: UUID,
        kind: AiOperationKind,
        idempotency_key: str | None,
        request_hash: str,
        invoke: Callable[[ProviderConfig, str, TaskState], Awaitable[ServiceResult]],
        persist: PersistResult,
    ) -> AiOperation:
        existing = await self._idempotent_operation(
            owner_id, task.id, kind, idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        lease = await self._call_lock.acquire(owner_id)
        async with lease:
            existing = await self._idempotent_operation(
                owner_id, task.id, kind, idempotency_key, request_hash
            )
            if existing is not None:
                return existing
            operation = None
            if self._queued_operation_id is not None:
                operation = await self.get_owned_operation(self._queued_operation_id, owner_id)
                await self._session.refresh(operation)
                if operation.status != AiOperationStatus.QUEUED:
                    return operation
            await self._session.refresh(task, with_for_update=True)
            config, model_identifier = await self._provider_context(owner_id)
            initial_state = TaskState(task.state)
            try:
                assert_transition(initial_state, _running_state(kind))
            except ValueError as exc:
                raise TaskAiExecutionError(
                    "invalid_task_state",
                    "The task is not ready for this AI operation",
                    409,
                ) from exc
            if operation is None:
                operation = AiOperation(
                    owner_id=owner_id,
                    task_id=task.id,
                    task_name=task.name,
                    kind=kind,
                    status=AiOperationStatus.RUNNING,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    initial_task_state=initial_state,
                    running_task_state=_running_state(kind),
                    completed_task_state=None,
                    error_details={},
                    started_at=datetime.now(UTC),
                )
            else:
                claimed = await self._session.execute(
                    update(AiOperation)
                    .where(
                        AiOperation.id == operation.id,
                        AiOperation.status == AiOperationStatus.QUEUED,
                    )
                    .values(status=AiOperationStatus.RUNNING, started_at=datetime.now(UTC))
                )
                if not claimed.rowcount:
                    await self._session.refresh(operation)
                    return operation
            task.state = _running_state(kind)
            self._session.add(operation)
            try:
                await self._session.commit()
            except IntegrityError:
                await self._session.rollback()
                existing = await self._idempotent_operation(
                    owner_id, task.id, kind, idempotency_key, request_hash
                )
                if existing is not None:
                    return existing
                raise
            try:
                result = await invoke(config, model_identifier, initial_state)
                resource_type, resource_id = await persist(result)
                task.state = result.state.succeeded
                operation.status = AiOperationStatus.SUCCEEDED
                operation.completed_task_state = result.state.succeeded
                operation.resource_type = resource_type
                operation.resource_id = resource_id
                operation.provider_request_id = result.metadata.provider_request_id
                operation.completed_at = datetime.now(UTC)
                await self._session.commit()
                await self._session.refresh(operation)
                return operation
            except AiOperationFailed as exc:
                await self._record_failure(task, operation, exc.error.as_dict())
                raise TaskAiExecutionError(
                    exc.error.code,
                    exc.error.message,
                    _provider_error_status(exc.error.code),
                    details={
                        **exc.error.details,
                        "retryable": exc.error.retryable,
                        "operation_id": str(operation.id),
                    },
                ) from exc
            except (ValueError, ValidationError) as exc:
                error = {
                    "code": "invalid_ai_operation",
                    "message": "AI operation inputs do not match the task state or constraints",
                    "details": {},
                }
                await self._record_failure(task, operation, error)
                raise TaskAiExecutionError(
                    error["code"],
                    error["message"],
                    409,
                    details={"operation_id": str(operation.id)},
                ) from exc
            except asyncio.CancelledError:
                operation_id = operation.id
                task_id = task.id
                await asyncio.shield(self._record_cancellation(task_id, operation_id))
                raise
            except Exception as exc:
                operation_id = operation.id
                task_id = task.id
                await self._session.rollback()
                recovered_operation = await self._session.get(AiOperation, operation_id)
                if (
                    recovered_operation is not None
                    and recovered_operation.status == AiOperationStatus.SUCCEEDED
                ):
                    return recovered_operation
                recovered_task = await self._session.get(RewriteTask, task_id)
                if recovered_operation is not None and recovered_task is not None:
                    await self._record_failure(
                        recovered_task,
                        recovered_operation,
                        {
                            "code": "ai_operation_internal_error",
                            "message": "The AI operation could not be completed",
                            "details": {},
                        },
                    )
                raise TaskAiExecutionError(
                    "ai_operation_internal_error",
                    "The AI operation could not be completed",
                    500,
                    details={"operation_id": str(operation_id)},
                ) from exc

    async def _record_failure(
        self,
        task: RewriteTask,
        operation: AiOperation,
        error: dict[str, Any],
        *,
        status: AiOperationStatus = AiOperationStatus.FAILED,
    ) -> None:
        task.state = operation.initial_task_state
        operation.status = status
        operation.completed_task_state = operation.initial_task_state
        operation.error_code = error["code"]
        operation.error_message = error["message"]
        operation.error_details = error.get("details", {})
        operation.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def _record_cancellation(self, task_id: UUID, operation_id: UUID) -> None:
        await self._session.rollback()
        operation = await self._session.get(AiOperation, operation_id)
        task = await self._session.get(RewriteTask, task_id)
        if operation is not None and task is not None:
            await self._record_failure(
                task,
                operation,
                {
                    "code": "ai_operation_cancelled",
                    "message": "The AI operation was cancelled",
                    "details": {},
                },
                status=AiOperationStatus.CANCELLED,
            )

    async def _provider_context(self, owner_id: UUID) -> tuple[ProviderConfig, str]:
        setting = await self._session.scalar(
            select(ProviderSetting).where(ProviderSetting.member_id == owner_id)
        )
        if setting is None:
            raise TaskAiExecutionError(
                "provider_not_configured",
                "Configure an API key, request URL and model before starting an AI operation",
                409,
            )
        try:
            api_key = self._cipher.decrypt(setting.encrypted_api_key)
        except InvalidEncryptedValueError as exc:
            raise TaskAiExecutionError(
                "provider_configuration_invalid",
                "The saved provider configuration must be replaced",
                409,
            ) from exc
        try:
            base_url = await self._provider_url_policy.validate(setting.base_url)
        except ProviderUrlPolicyError as exc:
            raise TaskAiExecutionError(
                "provider_configuration_invalid",
                "The saved provider request URL is not allowed",
                409,
            ) from exc
        return ProviderConfig(
            api_key=api_key, base_url=base_url, timeout_seconds=setting.timeout_seconds
        ), setting.model_id

    async def _analysis(self, task_id: UUID, analysis_id: UUID | None) -> AnalysisRecord:
        conditions = [AnalysisRecord.task_id == task_id]
        if analysis_id is None:
            conditions.append(AnalysisRecord.is_selected.is_(True))
        else:
            conditions.append(AnalysisRecord.id == analysis_id)
        record = await self._session.scalar(select(AnalysisRecord).where(*conditions))
        if record is None:
            raise TaskAiExecutionError("analysis_not_found", "Analysis was not found", 404)
        return record

    async def _has_first_draft(self, task_id: UUID) -> bool:
        value = await self._session.scalar(
            select(func.count())
            .select_from(ScriptVersion)
            .where(
                ScriptVersion.task_id == task_id,
                ScriptVersion.kind == "first_draft",
            )
        )
        return bool(value)

    async def _idempotent_operation(
        self,
        owner_id: UUID,
        task_id: UUID,
        kind: AiOperationKind,
        idempotency_key: str | None,
        request_hash: str,
    ) -> AiOperation | None:
        if idempotency_key is None:
            return None
        operation = await self._session.scalar(
            select(AiOperation).where(
                AiOperation.owner_id == owner_id,
                AiOperation.task_id == task_id,
                AiOperation.kind == kind,
                AiOperation.idempotency_key == idempotency_key,
            )
        )
        if operation is not None and operation.request_hash != request_hash:
            raise TaskAiExecutionError(
                "idempotency_key_reused",
                "The idempotency key was already used with different inputs",
                409,
            )
        return operation


def _task_snapshot(
    task: RewriteTask, *, has_first_draft: bool, state: TaskState | None = None
) -> TaskAiSnapshot:
    return TaskAiSnapshot(
        id=task.id,
        state=state or TaskState(task.state),
        source_text=task.source_text,
        creative_settings=CreativeSettings.model_validate(task.creative_settings),
        has_first_draft=has_first_draft,
    )


def _stored_analysis(record: AnalysisRecord) -> AnalysisResult:
    try:
        return TypeAdapter(AnalysisResult).validate_python(record.payload)
    except ValidationError as exc:
        raise TaskAiExecutionError(
            "analysis_invalid", "The saved analysis is invalid and must be regenerated", 409
        ) from exc


def _stored_suggestion(record: SuggestionRecord) -> Suggestion:
    return Suggestion(
        suggestion_id=record.suggestion_key,
        priority=record.priority,
        title=record.title,
        analysis_issue_ids=record.analysis_issue_ids,
        problem=record.problem,
        direction=record.direction,
        rationale=record.reason,
        impact_scope=record.impact_scope,
        example=record.example or "无",
    )


def _version_record(task_id: UUID, result: VersionServiceResult) -> ScriptVersion:
    return ScriptVersion(
        task_id=task_id,
        parent_id=result.parent_version_id,
        kind=result.kind,
        content=result.content,
        instruction=result.instruction,
        provenance={
            **result.provenance,
            "model_identifier": result.metadata.model_identifier,
            "prompt_template_version": result.metadata.prompt_template_version,
        },
        validation_status=result.validation_status,
        validation_details=result.validation.model_dump(mode="json"),
        is_current_final=False,
    )


def _running_state(kind: AiOperationKind) -> TaskState:
    return {
        AiOperationKind.ANALYSIS: TaskState.ANALYZING,
        AiOperationKind.SUGGESTIONS: TaskState.SUGGESTING,
        AiOperationKind.FIRST_DRAFT: TaskState.GENERATING,
        AiOperationKind.REVISION: TaskState.REVISING,
    }[kind]


def _provider_error_status(code: str) -> int:
    if code == "provider_authentication_failed":
        return 401
    if code in {
        "provider_invalid_request",
        "provider_model_unavailable",
        "provider_invalid_endpoint",
    }:
        return 400
    if code == "provider_rate_limited":
        return 429
    return 502


def _request_hash(kind: AiOperationKind, task_id: UUID, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {
            "kind": kind,
            "task_id": str(task_id),
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
