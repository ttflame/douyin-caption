"""Durable, member-scoped submission and queue controls."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import ProviderSetting
from app.modules.tasks.ai_operations import TaskAiExecutionError, _request_hash, _running_state
from app.modules.tasks.domain import (
    AiOperationKind,
    AiOperationStatus,
    TaskState,
    assert_transition,
)
from app.modules.tasks.models import AiOperation, RewriteTask
from app.modules.tasks.schemas import (
    AnalysisSubmit,
    FirstDraftSubmit,
    RevisionSubmit,
    SuggestionsSubmit,
)

PAYLOAD_TYPES = {
    AiOperationKind.ANALYSIS: AnalysisSubmit,
    AiOperationKind.SUGGESTIONS: SuggestionsSubmit,
    AiOperationKind.FIRST_DRAFT: FirstDraftSubmit,
    AiOperationKind.REVISION: RevisionSubmit,
}
ACTIVE_STATUSES = (AiOperationStatus.QUEUED, AiOperationStatus.RUNNING)


class AiQueueService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def submit(
        self,
        task: RewriteTask,
        owner_id: UUID,
        kind: AiOperationKind,
        payload: BaseModel,
        idempotency_key: str | None,
    ) -> AiOperation:
        if task.owner_id != owner_id:
            raise TaskAiExecutionError("task_not_found", "文案不存在", 404)
        data = payload.model_dump(mode="json")
        request_hash = _request_hash(kind, task.id, data)
        existing = await self._existing(task.id, owner_id, kind, idempotency_key, request_hash)
        if existing is not None:
            return existing
        await self.session.refresh(task, with_for_update=True)
        active = await self.session.scalar(
            select(AiOperation.id).where(
                AiOperation.task_id == task.id, AiOperation.status.in_(ACTIVE_STATUSES)
            )
        )
        if active:
            raise TaskAiExecutionError(
                "ai_operation_in_progress", "该文案已有排队或执行中的任务", 409
            )
        try:
            assert_transition(TaskState(task.state), _running_state(kind))
        except ValueError as exc:
            raise TaskAiExecutionError(
                "invalid_task_state", "当前文案尚不能执行此操作", 409
            ) from exc
        if not await self.session.scalar(
            select(ProviderSetting.id).where(ProviderSetting.member_id == owner_id)
        ):
            raise TaskAiExecutionError("provider_setting_not_found", "请先配置模型连接", 409)
        operation = AiOperation(
            owner_id=owner_id,
            task_id=task.id,
            task_name=task.name,
            kind=kind,
            status=AiOperationStatus.QUEUED,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_payload=data,
            initial_task_state=task.state,
            running_task_state=_running_state(kind),
            error_details={},
            created_at=datetime.now(UTC),
            started_at=None,
        )
        self.session.add(operation)
        task_id = task.id
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self._existing(task_id, owner_id, kind, idempotency_key, request_hash)
            if existing is not None:
                return existing
            raise TaskAiExecutionError(
                "ai_operation_in_progress", "该文案已有排队或执行中的任务", 409
            ) from exc
        await self.session.refresh(operation)
        return operation

    async def _existing(self, task_id, owner_id, kind, key, request_hash):
        if key is None:
            return None
        operation = await self.session.scalar(
            select(AiOperation).where(
                AiOperation.task_id == task_id,
                AiOperation.owner_id == owner_id,
                AiOperation.kind == kind,
                AiOperation.idempotency_key == key,
            )
        )
        if operation is not None and operation.request_hash != request_hash:
            raise TaskAiExecutionError("idempotency_key_reused", "重复请求的参数不一致", 409)
        return operation

    async def owned(self, owner_id: UUID, operation_id: UUID) -> AiOperation:
        operation = await self.session.scalar(
            select(AiOperation).where(
                AiOperation.id == operation_id, AiOperation.owner_id == owner_id
            )
        )
        if operation is None:
            raise TaskAiExecutionError("operation_not_found", "任务不存在", 404)
        return operation

    async def list_owned(self, owner_id: UUID) -> list[AiOperation]:
        active = list(
            (
                await self.session.scalars(
                    select(AiOperation)
                    .where(
                        AiOperation.owner_id == owner_id, AiOperation.status.in_(ACTIVE_STATUSES)
                    )
                    .order_by(AiOperation.created_at, AiOperation.id)
                )
            ).all()
        )
        recent = list(
            (
                await self.session.scalars(
                    select(AiOperation)
                    .where(
                        AiOperation.owner_id == owner_id, AiOperation.status.not_in(ACTIVE_STATUSES)
                    )
                    .order_by(AiOperation.completed_at.desc(), AiOperation.id)
                    .limit(30)
                )
            ).all()
        )
        return active + recent

    async def clear_completed(self, owner_id: UUID) -> None:
        await self.session.execute(
            delete(AiOperation).where(
                AiOperation.owner_id == owner_id,
                AiOperation.status.not_in(ACTIVE_STATUSES),
            )
        )
        await self.session.commit()

    async def cancel(self, owner_id: UUID, operation_id: UUID) -> AiOperation:
        operation = await self.owned(owner_id, operation_id)
        changed = await self.session.execute(
            update(AiOperation)
            .where(AiOperation.id == operation.id, AiOperation.status == AiOperationStatus.QUEUED)
            .values(status=AiOperationStatus.CANCELLED, completed_at=datetime.now(UTC))
        )
        if not changed.rowcount:
            raise TaskAiExecutionError(
                "operation_not_queued", "任务已开始或结束，无法取消排队", 409
            )
        await self.session.commit()
        await self.session.refresh(operation)
        return operation

    async def retry(self, owner_id: UUID, operation_id: UUID, key: str | None) -> AiOperation:
        operation = await self.owned(owner_id, operation_id)
        if operation.status not in (AiOperationStatus.FAILED, AiOperationStatus.CANCELLED):
            raise TaskAiExecutionError("operation_not_retryable", "只能重试失败或已取消的任务", 409)
        # Old synchronous operations did not persist request inputs.
        if not operation.request_payload and operation.kind != AiOperationKind.ANALYSIS:
            raise TaskAiExecutionError("operation_inputs_missing", "请回到文案页面重新提交", 409)
        task = await self.session.get(RewriteTask, operation.task_id)
        return await self.submit(
            task,
            owner_id,
            AiOperationKind(operation.kind),
            PAYLOAD_TYPES[operation.kind].model_validate(operation.request_payload),
            key,
        )
