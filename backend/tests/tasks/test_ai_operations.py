import asyncio
import ipaddress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.provider_url import ProviderUrlPolicy
from app.modules.ai.dto import (
    Analysis,
    AnalysisConclusion,
    CompletionRequest,
    CompletionResult,
    ContentHighlight,
    ContentOverview,
    ExpressionAnalysis,
    ParagraphFinding,
    RiskIssue,
    StructureMap,
    StructureSegment,
)
from app.modules.identity.models import Member, ProviderSetting
from app.modules.identity.security import ApiKeyCipher
from app.modules.tasks.ai_lock import MemberAiCallLock
from app.modules.tasks.ai_operations import (
    STALE_OPERATION_AFTER,
    TaskAiExecutionError,
    TaskAiOperationService,
    _stored_analysis,
)
from app.modules.tasks.ai_service import TaskAiService
from app.modules.tasks.domain import AiOperationStatus, TaskState
from app.modules.tasks.models import (
    AiOperation,
    AnalysisRecord,
    LockedFragment,
    RewriteTask,
    ScriptVersion,
)
from app.modules.tasks.router import TaskApiError, _assert_no_active_ai
from app.modules.tasks.schemas import AnalysisSubmit, CreativeSettings, RevisionSubmit


class FakeRedis:
    async def set(self, name, value, *, nx, ex):
        return True

    async def eval(self, script, numkeys, *keys_and_args):
        return 1


class FakeProvider:
    def __init__(self, response: CompletionResult | BaseException) -> None:
        self.response = response
        self.calls = 0
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls += 1
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def analysis() -> Analysis:
    return Analysis(
        content_overview=ContentOverview(
            theme="主题",
            core_viewpoint="观点",
            target_audience="受众",
            expected_action="行动",
        ),
        structure_map=StructureMap(
            segments=[
                StructureSegment(
                    segment_id="seg-1",
                    kind="主体",
                    source_excerpt="原文",
                    purpose="说明",
                )
            ]
        ),
        paragraph_analysis=[ParagraphFinding(segment_id="seg-1", relationship="主体", issues=[])],
        expression_analysis=ExpressionAnalysis(
            persona_consistency="一致",
            language_style="自然",
            spoken_fluency="流畅",
            emotional_intensity="适中",
            information_density="适中",
            spoken_rhythm="稳定",
        ),
        content_highlights=[ContentHighlight(excerpt="原文", reason="清晰")],
        problems_and_risks=[
            RiskIssue(
                issue_id="issue-1",
                category="repetition",
                description="重复",
                source_excerpt="原文",
            )
        ],
        conclusion=AnalysisConclusion(summary="结论", key_issue_ids=["issue-1"]),
    )


async def database_context(response: CompletionResult | BaseException):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def register_char_length(connection, _record) -> None:
        connection.create_function("char_length", 1, len)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    session = sessions()
    cipher = ApiKeyCipher("test-encryption-secret")
    member = Member(
        username=f"member-{uuid4()}",
        display_name="Member",
        password_hash="hash",
        role="member",
        is_active=True,
    )
    session.add(member)
    await session.flush()
    session.add(
        ProviderSetting(
            member_id=member.id,
            encrypted_api_key=cipher.encrypt("member-secret"),
            base_url="https://provider.example/v1",
            model_id="model-id",
        )
    )
    task = RewriteTask(
        owner_id=member.id,
        name="Task",
        source_text="原文",
        creative_settings=CreativeSettings(target_characters=300).model_dump(mode="json"),
        state=TaskState.DRAFT,
    )
    session.add(task)
    await session.commit()
    provider = FakeProvider(response)
    operations = TaskAiOperationService(
        session,
        MemberAiCallLock(FakeRedis()),
        ai_service=TaskAiService(provider_factory=lambda _: provider),
        cipher=cipher,
        provider_url_policy=ProviderUrlPolicy(
            resolver=lambda _hostname, _port: _public_addresses()
        ),
    )
    return engine, session, member, task, provider, operations


async def _public_addresses():
    return {ipaddress.ip_address("93.184.216.34")}


async def test_provider_context_uses_saved_member_timeout() -> None:
    engine, session, member, _, _, operations = await database_context(CompletionResult(text="ok"))
    try:
        setting = await session.scalar(
            select(ProviderSetting).where(ProviderSetting.member_id == member.id)
        )
        setting.timeout_seconds = 420
        await session.commit()
        config, model = await operations._provider_context(member.id)
        assert config.timeout_seconds == 420
        assert model == "model-id"
    finally:
        await session.close()
        await engine.dispose()


def test_historical_structured_analysis_remains_readable():
    original = analysis()
    record = AnalysisRecord(payload=original.model_dump(mode="json"))
    assert _stored_analysis(record) == original


@pytest.mark.asyncio
async def test_operation_persists_success_and_reuses_idempotency_key() -> None:
    response = CompletionResult(
        text="1. 开头：提出问题。\n2. 正文：给出方法。", provider_request_id="req-1"
    )
    engine, session, member, task, provider, operations = await database_context(response)
    try:
        first = await operations.analyze(task, member.id, AnalysisSubmit(), "same-key")
        second = await operations.analyze(task, member.id, AnalysisSubmit(), "same-key")

        assert first.id == second.id
        assert first.status == AiOperationStatus.SUCCEEDED
        assert first.resource_type == "analysis"
        assert provider.calls == 1
        assert task.state == TaskState.ANALYSIS_READY
        records = (await session.scalars(select(AnalysisRecord))).all()
        assert len(records) == 1
        assert records[0].payload == {"content": response.text}
        assert _stored_analysis(records[0]).content == response.text
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_idempotency_key_rejects_different_inputs() -> None:
    response = CompletionResult(text=analysis().model_dump_json())
    engine, session, member, task, provider, operations = await database_context(response)
    try:
        await operations.analyze(task, member.id, AnalysisSubmit(), "same-key")
        task.source_text = "different source"
        with pytest.raises(TaskAiExecutionError) as caught:
            await operations.analyze(
                task,
                member.id,
                AnalysisSubmit(),
                "same-key",
            )
        assert caught.value.code == "idempotency_key_reused"
        assert provider.calls == 1
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_unexpected_failure_is_safe_and_restores_task_state() -> None:
    engine, session, member, task, _, operations = await database_context(
        RuntimeError("provider leaked secret text")
    )
    try:
        with pytest.raises(TaskAiExecutionError) as caught:
            await operations.analyze(task, member.id, AnalysisSubmit(), None)

        await session.refresh(task)
        operation = await session.scalar(select(AiOperation))
        assert task.state == TaskState.DRAFT
        assert operation is not None
        assert operation.status == AiOperationStatus.FAILED
        assert operation.error_code == "ai_operation_internal_error"
        assert "provider leaked" not in operation.error_message
        assert "provider leaked" not in caught.value.message
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_call_records_cancelled_and_restores_task() -> None:
    engine, session, member, task, _, operations = await database_context(asyncio.CancelledError())
    try:
        with pytest.raises(asyncio.CancelledError):
            await operations.analyze(task, member.id, AnalysisSubmit(), None)

        await session.refresh(task)
        operation = await session.scalar(select(AiOperation))
        assert task.state == TaskState.DRAFT
        assert operation is not None
        assert operation.status == AiOperationStatus.CANCELLED
        assert operation.error_code == "ai_operation_cancelled"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_running_operation_is_failed_and_task_is_restored() -> None:
    engine, session, member, task, _, operations = await database_context(
        CompletionResult(text=analysis().model_dump_json())
    )
    try:
        task.state = TaskState.ANALYZING
        stale = AiOperation(
            owner_id=member.id,
            task_id=task.id,
            kind="analysis",
            status="running",
            idempotency_key=None,
            request_hash="0" * 64,
            initial_task_state="draft",
            running_task_state="analyzing",
            completed_task_state=None,
            error_details={},
            started_at=datetime.now(UTC) - STALE_OPERATION_AFTER - timedelta(seconds=1),
        )
        session.add(stale)
        await session.commit()

        assert await operations.recover_stale_operations(member.id) == 1
        await session.refresh(task)
        await session.refresh(stale)
        assert task.state == TaskState.DRAFT
        assert stale.status == AiOperationStatus.FAILED
        assert stale.error_code == "ai_operation_stale"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_mutation_is_blocked_during_active_operation() -> None:
    engine, session, member, task, _, _ = await database_context(
        CompletionResult(text=analysis().model_dump_json())
    )
    try:
        session.add(
            AiOperation(
                owner_id=member.id,
                task_id=task.id,
                kind="analysis",
                status="running",
                idempotency_key=None,
                request_hash="0" * 64,
                initial_task_state="draft",
                running_task_state="analyzing",
                completed_task_state=None,
                error_details={},
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()
        with pytest.raises(TaskApiError) as caught:
            await _assert_no_active_ai(session, task.id)
        assert caught.value.code == "ai_operation_in_progress"
        assert caught.value.status_code == 409
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_revision_keeps_locks_created_on_an_older_version() -> None:
    engine, session, member, task, provider, operations = await database_context(
        CompletionResult(text="当前版本，必须保留")
    )
    try:
        first = ScriptVersion(
            task_id=task.id,
            parent_id=None,
            kind="first_draft",
            content="最早版本，必须保留",
            provenance={},
            validation_status="not_checked",
            validation_details={},
            is_current_final=False,
        )
        session.add(first)
        await session.flush()
        current = ScriptVersion(
            task_id=task.id,
            parent_id=first.id,
            kind="ai_revision",
            content="当前版本",
            provenance={},
            validation_status="satisfied",
            validation_details={},
            is_current_final=False,
        )
        session.add(current)
        await session.flush()
        session.add(
            LockedFragment(
                task_id=task.id,
                source_version_id=first.id,
                text="必须保留",
                start_offset=5,
                end_offset=9,
                order_index=0,
            )
        )
        task.state = TaskState.EDITING
        await session.commit()

        operation = await operations.revise(
            task,
            member.id,
            RevisionSubmit(
                parent_version_id=current.id,
                scope="full",
                instruction="继续修改",
            ),
            None,
        )

        assert operation.status == AiOperationStatus.SUCCEEDED
        assert "必须保留" in provider.requests[0].messages[1].content
    finally:
        await session.close()
        await engine.dispose()
