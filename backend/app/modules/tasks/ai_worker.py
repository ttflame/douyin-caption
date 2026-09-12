"""Database-backed worker; HTTP requests only submit work."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from app.modules.identity.models import Member
from app.modules.tasks.ai_lock import AiLockUnavailableError, MemberAiCallBusyError
from app.modules.tasks.ai_operations import TaskAiExecutionError, TaskAiOperationService
from app.modules.tasks.ai_queue import ACTIVE_STATUSES, PAYLOAD_TYPES
from app.modules.tasks.domain import AiOperationStatus
from app.modules.tasks.models import AiOperation, RewriteTask

logger = logging.getLogger(__name__)


class AiQueueWorker:
    def __init__(
        self, sessions, call_lock, *, ai_service=None, cipher=None, provider_url_policy=None
    ):
        self.sessions = sessions
        self.call_lock = call_lock
        self.service_options = {
            "ai_service": ai_service,
            "cipher": cipher,
            "provider_url_policy": provider_url_policy,
        }
        self.jobs: dict[UUID, asyncio.Task] = {}

    async def run(self) -> None:
        try:
            while True:
                try:
                    await self.tick()
                except Exception as exc:
                    logger.warning("AI queue polling failed (%s)", type(exc).__name__)
                await asyncio.sleep(1)
        finally:
            for job in self.jobs.values():
                job.cancel()
            await asyncio.gather(*self.jobs.values(), return_exceptions=True)

    async def tick(self) -> None:
        for job in self.jobs.values():
            if job.done() and not job.cancelled() and (error := job.exception()):
                logger.warning("AI queue job failed (%s)", type(error).__name__)
        self.jobs = {owner: job for owner, job in self.jobs.items() if not job.done()}
        async with self.sessions() as session:
            service = TaskAiOperationService(session, self.call_lock, **self.service_options)
            owners = (
                await session.scalars(
                    select(AiOperation.owner_id)
                    .where(AiOperation.status == AiOperationStatus.RUNNING)
                    .distinct()
                )
            ).all()
            for owner in owners:
                if owner not in self.jobs:
                    await service.recover_stale_operations(owner)
            rows = (
                await session.execute(
                    select(AiOperation.id, AiOperation.owner_id, AiOperation.status)
                    .where(AiOperation.status.in_(ACTIVE_STATUSES))
                    .order_by(AiOperation.created_at, AiOperation.id)
                )
            ).all()
        running_owners = {row.owner_id for row in rows if row.status == AiOperationStatus.RUNNING}
        seen = set(self.jobs) | running_owners
        for row in rows:
            if row.owner_id not in seen:
                seen.add(row.owner_id)
                self.jobs[row.owner_id] = asyncio.create_task(self.execute(row.id))

    async def execute(self, operation_id: UUID) -> None:
        async with self.sessions() as session:
            service = TaskAiOperationService(
                session, self.call_lock, queued_operation_id=operation_id, **self.service_options
            )
            try:
                operation = await session.get(AiOperation, operation_id)
                if operation is None or operation.status != AiOperationStatus.QUEUED:
                    return
                owner = await session.get(Member, operation.owner_id)
                if owner is None or not owner.is_active:
                    raise TaskAiExecutionError("member_disabled", "账户已停用，任务未执行", 403)
                task = await session.get(RewriteTask, operation.task_id)
                logger.info(
                    "AI operation started request_id=%s operation_id=%s task_id=%s owner_id=%s",
                    operation.request_id,
                    operation.id,
                    operation.task_id,
                    operation.owner_id,
                )
                payload = PAYLOAD_TYPES[operation.kind].model_validate(operation.request_payload)
                method = {
                    "analysis": service.analyze,
                    "suggestions": service.suggest,
                    "first_draft": service.create_first_draft,
                    "revision": service.revise,
                }[operation.kind]
                completed = await method(task, operation.owner_id, payload, None)
                logger.info(
                    "AI operation completed request_id=%s operation_id=%s task_id=%s "
                    "owner_id=%s status=%s",
                    operation.request_id,
                    operation.id,
                    operation.task_id,
                    operation.owner_id,
                    completed.status,
                )
            except (MemberAiCallBusyError, AiLockUnavailableError):
                # Leave work queued until the member lease becomes available.
                await session.rollback()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await session.rollback()
                code = (
                    exc.code
                    if isinstance(exc, TaskAiExecutionError)
                    else "ai_operation_internal_error"
                )
                message = (
                    exc.message if isinstance(exc, TaskAiExecutionError) else "任务执行失败，请重试"
                )
                # Execution records its own failures; handle errors during preparation here.
                saved_operation = await session.get(AiOperation, operation_id)
                if saved_operation is not None:
                    logger.warning(
                        "AI operation failed request_id=%s operation_id=%s task_id=%s "
                        "owner_id=%s code=%s",
                        saved_operation.request_id,
                        saved_operation.id,
                        saved_operation.task_id,
                        saved_operation.owner_id,
                        code,
                    )
                    await session.execute(
                        update(RewriteTask)
                        .where(
                            RewriteTask.id == saved_operation.task_id,
                            RewriteTask.state == saved_operation.running_task_state,
                        )
                        .values(state=saved_operation.initial_task_state)
                    )
                await session.execute(
                    update(AiOperation)
                    .where(
                        AiOperation.id == operation_id,
                        AiOperation.status == AiOperationStatus.QUEUED,
                    )
                    .values(
                        status=AiOperationStatus.FAILED,
                        error_code=code,
                        error_message=message,
                        error_details={"retryable": True},
                        completed_at=datetime.now(UTC),
                    )
                )
                await session.commit()
