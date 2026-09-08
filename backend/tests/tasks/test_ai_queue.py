import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_session
from app.modules.ai.dto import CompletionResult
from app.modules.identity.models import Member, ProviderSetting
from app.modules.identity.router import get_current_member
from app.modules.identity.security import ApiKeyCipher
from app.modules.tasks.ai_lock import InMemoryMemberAiCallLock
from app.modules.tasks.ai_operations import TaskAiExecutionError
from app.modules.tasks.ai_queue import AiQueueService
from app.modules.tasks.ai_service import TaskAiService
from app.modules.tasks.ai_worker import AiQueueWorker
from app.modules.tasks.domain import AiOperationKind
from app.modules.tasks.models import (
    AiOperation,
    AnalysisRecord,
    LockedFragment,
    RewriteTask,
    ScriptVersion,
    SuggestionRecord,
)
from app.modules.tasks.router import (
    TaskApiError,
    _assert_no_active_ai,
    router,
    task_exception_handler,
)
from app.modules.tasks.schemas import (
    AnalysisSubmit,
    CreativeSettings,
    FirstDraftSubmit,
    RevisionSubmit,
    SuggestionsSubmit,
)


class PublicUrlPolicy:
    async def validate(self, value):
        return value


class ControlledProvider:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Queue()
        self.release = asyncio.Event()
        self.fail = False
        self.responses = []

    async def complete(self, request):
        source = request.messages[-1].content
        self.calls.append(source)
        await self.started.put(source)
        await self.release.wait()
        if self.fail:
            raise RuntimeError("private provider failure")
        return CompletionResult(
            text=self.responses.pop(0) if self.responses else f"Analysis of {source}"
        )


@pytest.fixture
async def queue_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue.sqlite3'}")

    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_functions(connection, _):
        connection.create_function("char_length", 1, len)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    cipher = ApiKeyCipher("test-encryption-secret")
    provider = ControlledProvider()
    async with sessions() as session:
        members = [
            Member(username=name, display_name=name, password_hash="hash", is_active=True)
            for name in ("owner", "other")
        ]
        session.add_all(members)
        await session.flush()
        session.add_all(
            [
                ProviderSetting(
                    member_id=member.id,
                    encrypted_api_key=cipher.encrypt("secret"),
                    base_url="https://provider.example/v1",
                    model_id="test",
                )
                for member in members
            ]
        )
        tasks = [
            RewriteTask(
                owner_id=members[owner].id,
                name=name,
                source_text=name,
                state="draft",
                creative_settings=CreativeSettings(target_characters=300).model_dump(mode="json"),
            )
            for name, owner in (("first", 0), ("second", 0), ("other", 1))
        ]
        session.add_all(tasks)
        await session.commit()
    worker = AiQueueWorker(
        sessions,
        InMemoryMemberAiCallLock(),
        ai_service=TaskAiService(provider_factory=lambda _: provider),
        cipher=cipher,
        provider_url_policy=PublicUrlPolicy(),
    )
    yield sessions, members, tasks, worker, provider
    provider.release.set()
    for job in worker.jobs.values():
        job.cancel()
    await asyncio.gather(*worker.jobs.values(), return_exceptions=True)
    await engine.dispose()


async def enqueue(sessions, task):
    async with sessions() as session:
        saved = await session.get(RewriteTask, task.id)
        return await AiQueueService(session).submit(
            saved, task.owner_id, AiOperationKind.ANALYSIS, AnalysisSubmit(), str(uuid4())
        )


async def test_durable_queue_serializes_member_and_runs_other_members(queue_context):
    sessions, _, tasks, worker, provider = queue_context
    operations = [await enqueue(sessions, task) for task in tasks]
    assert all(item.status == "queued" and item.started_at is None for item in operations)
    assert provider.calls == []
    # All request sessions are closed before a fresh worker reads the persisted queue.
    await worker.tick()
    started = {await asyncio.wait_for(provider.started.get(), 2) for _ in range(2)}
    assert started == {"first", "other"}
    async with sessions() as session:
        second = await session.get(AiOperation, operations[1].id)
        assert second.status == "queued" and second.started_at is None
    provider.release.set()
    await asyncio.gather(*worker.jobs.values())
    await worker.tick()
    await asyncio.gather(*worker.jobs.values())
    assert provider.calls.index("first") < provider.calls.index("second")
    async with sessions() as session:
        rows = (await session.scalars(select(AiOperation))).all()
        assert all(
            item.status == "succeeded" and item.started_at and item.resource_id for item in rows
        )
        for task in tasks:
            record = await session.scalar(
                select(AnalysisRecord).where(AnalysisRecord.task_id == task.id)
            )
            assert record.payload == {"content": f"Analysis of {task.source_text}"}


async def test_queue_cancel_retry_idempotency_and_owner_isolation(queue_context):
    sessions, members, tasks, _, _ = queue_context
    async with sessions() as session:
        service = AiQueueService(session)
        task = await session.get(RewriteTask, tasks[0].id)
        operation = await service.submit(
            task, members[0].id, AiOperationKind.ANALYSIS, AnalysisSubmit(), "one"
        )
        duplicate = await service.submit(
            task, members[0].id, AiOperationKind.ANALYSIS, AnalysisSubmit(), "one"
        )
        assert duplicate.id == operation.id
        with pytest.raises(TaskAiExecutionError) as caught:
            await service.submit(
                task, members[0].id, AiOperationKind.ANALYSIS, AnalysisSubmit(), "two"
            )
        assert caught.value.status_code == 409
        with pytest.raises(TaskApiError):
            await _assert_no_active_ai(session, task.id)
        assert await service.list_owned(members[1].id) == []
        with pytest.raises(TaskAiExecutionError) as caught:
            await service.cancel(members[1].id, operation.id)
        assert caught.value.status_code == 404
        await service.cancel(members[0].id, operation.id)
        await _assert_no_active_ai(session, task.id)
        retried = await service.retry(members[0].id, operation.id, "retry")
        assert retried.id != operation.id and retried.status == "queued"
        assert (await service.retry(members[0].id, operation.id, "retry")).id == retried.id


async def test_failure_does_not_block_next_task_and_running_cannot_be_cancelled(queue_context):
    sessions, members, tasks, worker, provider = queue_context
    first = await enqueue(sessions, tasks[0])
    await enqueue(sessions, tasks[1])
    await worker.tick()
    await asyncio.wait_for(provider.started.get(), 2)
    async with sessions() as session:
        with pytest.raises(TaskAiExecutionError) as caught:
            await AiQueueService(session).cancel(members[0].id, first.id)
        assert caught.value.code == "operation_not_queued"
    provider.fail = True
    provider.release.set()
    await asyncio.gather(*worker.jobs.values())
    provider.fail = False
    await worker.tick()
    await asyncio.gather(*worker.jobs.values())
    async with sessions() as session:
        failed = await session.get(AiOperation, first.id)
        assert failed.status == "failed" and "private" not in failed.error_message
        assert (await session.get(RewriteTask, tasks[0].id)).state == "draft"
        assert (await session.get(RewriteTask, tasks[1].id)).state == "analysis_ready"


async def test_submit_http_returns_before_provider_and_worker_survives_client_close(queue_context):
    sessions, members, tasks, worker, provider = queue_context
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(TaskApiError, task_exception_handler)

    async def session_dependency():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_member] = lambda: members[0]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/tasks/{tasks[0].id}/analysis", json={}, headers={"Idempotency-Key": "http"}
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert response.json()["started_at"] is None
        assert provider.calls == []
    provider.release.set()
    await worker.tick()
    await asyncio.gather(*worker.jobs.values())
    async with sessions() as session:
        assert (await session.get(RewriteTask, tasks[0].id)).state == "analysis_ready"


async def test_all_workflow_stages_use_saved_queue_inputs(queue_context):
    sessions, members, tasks, worker, provider = queue_context
    provider.release.set()
    provider.responses = [
        "1. Analyze the opening.",
        json.dumps(
            {
                "suggestions": [
                    {
                        "suggestion_id": f"s{i}",
                        "priority": "primary",
                        "title": "Shorten",
                        "analysis_issue_ids": ["analysis"],
                        "problem": "Too long",
                        "direction": "Shorten it",
                        "rationale": "Clearer",
                        "impact_scope": "Opening",
                        "example": "Start directly",
                    }
                    for i in range(5)
                ]
            }
        ),
        "First draft",
        "Revised draft",
    ]
    resource_ids = []
    for kind in ("analysis", "suggestions", "first_draft", "revision"):
        async with sessions() as session:
            task = await session.get(RewriteTask, tasks[0].id)
            payload = {
                "analysis": AnalysisSubmit(),
                "suggestions": SuggestionsSubmit(member_context="saved context"),
                "first_draft": FirstDraftSubmit(member_requirements="saved requirements"),
            }.get(kind)
            if kind == "revision":
                payload = RevisionSubmit(
                    parent_version_id=resource_ids[-1], scope="full", instruction="saved revision"
                )
            operation = await AiQueueService(session).submit(
                task, members[0].id, AiOperationKind(kind), payload, kind
            )
            operation_id = operation.id
        await worker.tick()
        await asyncio.gather(*worker.jobs.values())
        async with sessions() as session:
            operation = await session.get(AiOperation, operation_id)
            assert operation.status == "succeeded", operation.error_message
            resource_ids.append(operation.resource_id)
    assert "saved context" in provider.calls[1]
    assert "saved requirements" in provider.calls[2]
    assert "saved revision" in provider.calls[3]
    async with sessions() as session:
        version = await session.get(ScriptVersion, resource_ids[-1])
        assert version.parent_id == resource_ids[-2]
        assert version.content == "Revised draft"


async def test_competing_workers_do_not_duplicate_a_provider_call(queue_context):
    sessions, _, tasks, worker, provider = queue_context
    await enqueue(sessions, tasks[0])
    competitor = AiQueueWorker(sessions, worker.call_lock, **worker.service_options)
    await asyncio.gather(worker.tick(), competitor.tick())
    await asyncio.wait_for(provider.started.get(), 2)
    provider.release.set()
    await asyncio.gather(*worker.jobs.values(), *competitor.jobs.values())
    assert provider.calls == ["first"]


async def test_cancelled_queue_entry_is_never_sent_to_provider(queue_context):
    sessions, members, tasks, worker, provider = queue_context
    operation = await enqueue(sessions, tasks[0])
    async with sessions() as session:
        await AiQueueService(session).cancel(members[0].id, operation.id)
    await worker.execute(operation.id)
    assert provider.calls == []


async def test_continue_suggestions_preserves_selected_rows_and_notes(queue_context):
    sessions, members, tasks, worker, provider = queue_context
    async with sessions() as session:
        task = await session.get(RewriteTask, tasks[0].id)
        task.state = "suggestions_ready"
        analysis = AnalysisRecord(
            task_id=task.id,
            sequence=1,
            payload={"content": "分析"},
            is_selected=True,
            prompt_template_version="test",
            model_identifier="test",
        )
        session.add(analysis)
        await session.flush()
        rows = [
            SuggestionRecord(
                task_id=task.id,
                analysis_id=analysis.id,
                suggestion_key=f"s{i}",
                analysis_issue_ids=["analysis"],
                priority="primary",
                title=f"原方案{i}",
                problem="原问题",
                direction="原方向",
                reason="原理由",
                impact_scope="正文",
                example="例子",
                decision="accepted" if i == 0 else "pending",
                member_note="成员备注" if i == 0 else None,
            )
            for i in range(5)
        ]
        session.add_all(rows)
        await session.commit()
        fixed_id, analysis_id = rows[0].id, analysis.id
    provider.release.set()
    for round_number in range(2):
        provider.responses = [
            json.dumps(
                {
                    "suggestions": [
                        {
                            "suggestion_id": "s0" if i == 0 else f"new-{round_number}-{i}",
                            "priority": "optional",
                            "title": f"新方案{round_number}-{i}",
                            "analysis_issue_ids": ["analysis"],
                            "problem": "新问题",
                            "direction": "新方向",
                            "rationale": "新理由",
                            "impact_scope": "开头",
                            "example": "新例子",
                        }
                        for i in range(5)
                    ]
                }
            )
        ]
        async with sessions() as session:
            task = await session.get(RewriteTask, tasks[0].id)
            operation = await AiQueueService(session).submit(
                task,
                members[0].id,
                AiOperationKind.SUGGESTIONS,
                SuggestionsSubmit(analysis_id=analysis_id),
                str(uuid4()),
            )
            operation_id = operation.id
        await worker.tick()
        await asyncio.gather(*worker.jobs.values())
        async with sessions() as session:
            assert (await session.get(AiOperation, operation_id)).status == "succeeded"
            rows = (
                await session.scalars(
                    select(SuggestionRecord).where(SuggestionRecord.task_id == tasks[0].id)
                )
            ).all()
            assert len(rows) == 5
            fixed = await session.get(SuggestionRecord, fixed_id)
            assert (
                fixed.title,
                fixed.direction,
                fixed.priority,
                fixed.decision,
                fixed.member_note,
            ) == ("原方案0", "原方向", "primary", "accepted", "成员备注")
            assert all(
                row.suggestion_key.startswith(f"new-{round_number}")
                for row in rows
                if row.id != fixed_id
            )
    assert "fixed_suggestions" in provider.calls[0]
    assert "成员备注" in provider.calls[0]


@pytest.mark.parametrize(
    "candidate, expected",
    [
        ("保留乙。新开头。保留甲。", "succeeded"),
        ("保留乙。保留甲改了。", "failed"),
    ],
)
async def test_sentence_locks_can_move_but_invalid_versions_are_not_saved(
    queue_context, candidate, expected
):
    sessions, members, tasks, worker, provider = queue_context
    async with sessions() as session:
        task = await session.get(RewriteTask, tasks[0].id)
        task.state = "editing"
        version = ScriptVersion(
            task_id=task.id,
            kind="first_draft",
            content="首句。保留甲。保留乙。",
            provenance={},
            validation_status="not_checked",
            validation_details={},
            is_current_final=False,
        )
        session.add(version)
        await session.flush()
        session.add_all(
            [
                LockedFragment(
                    task_id=task.id,
                    source_version_id=version.id,
                    text=text,
                    start_offset=start,
                    end_offset=start + len(text),
                    order_index=i,
                )
                for i, (text, start) in enumerate((("保留甲。", 3), ("保留乙。", 7)))
            ]
        )
        await session.commit()
        parent_id = version.id
        operation = await AiQueueService(session).submit(
            task,
            members[0].id,
            AiOperationKind.REVISION,
            RevisionSubmit(parent_version_id=parent_id, scope="full", instruction="优化未锁定部分"),
            str(uuid4()),
        )
        operation_id = operation.id
    provider.responses = [candidate]
    provider.release.set()
    await worker.tick()
    await asyncio.gather(*worker.jobs.values())
    async with sessions() as session:
        operation = await session.get(AiOperation, operation_id)
        assert operation.status == expected
        versions = (
            await session.scalars(select(ScriptVersion).where(ScriptVersion.task_id == tasks[0].id))
        ).all()
        assert len(versions) == (2 if expected == "succeeded" else 1)
        assert (await session.get(ScriptVersion, parent_id)).content == "首句。保留甲。保留乙。"
        assert (await session.get(RewriteTask, tasks[0].id)).state == "editing"
        if expected == "failed":
            assert operation.error_code == "locked_text_changed"
