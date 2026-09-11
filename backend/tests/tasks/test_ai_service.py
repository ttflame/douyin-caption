import json
from collections.abc import Iterable
from uuid import uuid4

import pytest

from app.modules.ai.dto import (
    Analysis,
    AnalysisConclusion,
    CompletionRequest,
    CompletionResult,
    ContentHighlight,
    ContentOverview,
    ExpressionAnalysis,
    LockedFragment,
    ParagraphFinding,
    ProviderUsage,
    RiskIssue,
    SelectedSuggestion,
    Selection,
    StructureMap,
    StructureSegment,
    Suggestion,
    SuggestionSet,
    TextAnalysis,
)
from app.modules.ai.errors import AiError, AiErrorCode
from app.modules.ai.provider import ProviderConfig
from app.modules.tasks.ai_service import (
    AiOperationFailed,
    LockedFragmentSnapshot,
    TaskAiService,
    TaskAiSnapshot,
    VersionAiSnapshot,
)
from app.modules.tasks.domain import (
    FirstDraftAlreadyExists,
    InvalidTaskTransition,
    TaskState,
    ValidationStatus,
    VersionKind,
)
from app.modules.tasks.schemas import CreativeSettings


class FakeProvider:
    def __init__(self, responses: Iterable[CompletionResult | AiError]) -> None:
        self.responses = iter(responses)
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, AiError):
            raise response
        return response


def settings() -> CreativeSettings:
    return CreativeSettings(target_characters=500)


def task(state: TaskState, *, has_first_draft: bool = False) -> TaskAiSnapshot:
    return TaskAiSnapshot(
        id=uuid4(),
        state=state,
        source_text="这是需要分析的原文",
        creative_settings=settings(),
        has_first_draft=has_first_draft,
    )


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
                    purpose="说明观点",
                )
            ]
        ),
        paragraph_analysis=[
            ParagraphFinding(segment_id="seg-1", relationship="主体段", issues=["重复"])
        ],
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
        conclusion=AnalysisConclusion(summary="压缩", key_issue_ids=["issue-1"]),
    )


def suggestion(index: int, issue_id: str = "issue-1") -> Suggestion:
    return Suggestion(
        suggestion_id=f"suggestion-{index}",
        priority="primary" if index == 0 else "optional",
        title="压缩",
        analysis_issue_ids=[issue_id],
        problem="重复",
        direction="删除",
        rationale="提升节奏",
        impact_scope="开头",
        example="直接说结论",
    )


def result(text: str) -> CompletionResult:
    return CompletionResult(
        text=text,
        provider_request_id="request-id",
        usage=ProviderUsage(input_tokens=12, output_tokens=8),
    )


def service(provider: FakeProvider) -> TaskAiService:
    return TaskAiService(provider_factory=lambda _: provider)


def provider_config() -> ProviderConfig:
    return ProviderConfig(api_key="member-secret", base_url="https://provider.example/v1")


@pytest.mark.asyncio
async def test_analyze_returns_persistable_result_and_state_plan() -> None:
    provider = FakeProvider([result("1. 开头提出问题。\n2. 正文给出方法。")])
    output = await service(provider).analyze(task(TaskState.DRAFT), provider_config(), "model-id")

    assert output.analysis.content == "1. 开头提出问题。\n2. 正文给出方法。"
    assert output.state.running == TaskState.ANALYZING
    assert output.state.succeeded == TaskState.ANALYSIS_READY
    assert output.state.failed == TaskState.DRAFT
    assert output.metadata.model_identifier == "model-id"
    assert output.metadata.input_tokens == 12
    assert "member-secret" not in repr(output)
    assert provider.requests[0].messages[0].content == "根据原文整理出来一个文案结构，逐条分析"


@pytest.mark.asyncio
async def test_empty_analysis_has_safe_error_and_restore_state() -> None:
    provider = FakeProvider([result("  \n")])
    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).analyze(task(TaskState.DRAFT), provider_config(), "model-id")

    assert caught.value.state.failed == TaskState.DRAFT
    assert caught.value.error.code == AiErrorCode.INVALID_RESPONSE
    assert caught.value.error.details == {"reason": "empty_content"}


async def test_text_analysis_supports_suggestions_and_first_draft() -> None:
    text_analysis = TextAnalysis(content="1. 开头的问题重复，应压缩。")
    suggestions = [suggestion(i, "analysis") for i in range(5)]
    provider = FakeProvider(
        [
            result(SuggestionSet(suggestions=suggestions).model_dump_json()),
            result("修改后的正文"),
        ]
    )
    ai = service(provider)
    output = await ai.suggest(
        task(TaskState.ANALYSIS_READY), text_analysis, provider_config(), "model"
    )
    assert len(output.suggestions.suggestions) == 5
    draft = await ai.create_first_draft(
        task(TaskState.SUGGESTIONS_READY),
        text_analysis,
        [SelectedSuggestion(suggestion=suggestions[0])],
        provider_config(),
        "model",
    )
    assert draft.content == "修改后的正文"


@pytest.mark.asyncio
async def test_suggestions_require_five_to_eight_valid_analysis_references() -> None:
    invalid = SuggestionSet(suggestions=[suggestion(i) for i in range(5)]).model_dump(mode="json")
    invalid["suggestions"][0]["analysis_issue_ids"] = ["unknown"]
    provider = FakeProvider([result(json.dumps(invalid))])

    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).suggest(
            task(TaskState.ANALYSIS_READY),
            analysis(),
            provider_config(),
            "model-id",
        )

    assert caught.value.error.code == AiErrorCode.INVALID_RESPONSE
    assert caught.value.state.failed == TaskState.ANALYSIS_READY


@pytest.mark.asyncio
async def test_valid_suggestions_are_ready_for_route_persistence() -> None:
    suggestions = SuggestionSet(suggestions=[suggestion(i) for i in range(5)])
    provider = FakeProvider([result(suggestions.model_dump_json())])

    output = await service(provider).suggest(
        task(TaskState.ANALYSIS_READY),
        analysis(),
        provider_config(),
        "model-id",
    )

    assert len(output.suggestions.suggestions) == 5
    assert output.state.running == TaskState.SUGGESTING
    assert output.state.succeeded == TaskState.SUGGESTIONS_READY


@pytest.mark.asyncio
async def test_first_draft_is_unique_before_provider_call() -> None:
    provider = FakeProvider([result("不会调用")])
    with pytest.raises(FirstDraftAlreadyExists):
        await service(provider).create_first_draft(
            task(TaskState.SUGGESTIONS_READY, has_first_draft=True),
            analysis(),
            [],
            provider_config(),
            "model-id",
        )
    assert provider.requests == []


@pytest.mark.asyncio
async def test_first_draft_returns_version_without_credentials() -> None:
    provider = FakeProvider([result("第一版正文")])
    selected = [SelectedSuggestion(suggestion=suggestion(0), note="温和一点")]
    output = await service(provider).create_first_draft(
        task(TaskState.SUGGESTIONS_READY),
        analysis(),
        selected,
        provider_config(),
        "model-id",
    )

    assert output.kind == VersionKind.FIRST_DRAFT
    assert output.parent_version_id is None
    assert output.state.succeeded == TaskState.EDITING
    assert output.provenance["selected_suggestion_ids"] == ["suggestion-0"]
    assert "member-secret" not in repr(output)


@pytest.mark.asyncio
async def test_first_draft_rejects_unknown_analysis_reference_before_call() -> None:
    provider = FakeProvider([result("不会调用")])
    selected = [SelectedSuggestion(suggestion=suggestion(0, issue_id="unknown"))]
    with pytest.raises(ValueError, match="unknown analysis issue"):
        await service(provider).create_first_draft(
            task(TaskState.SUGGESTIONS_READY),
            analysis(),
            selected,
            provider_config(),
            "model-id",
        )
    assert provider.requests == []


@pytest.mark.asyncio
async def test_regeneration_from_suggestions_creates_a_child_revision() -> None:
    parent = VersionAiSnapshot(id=uuid4(), content="旧稿包含必须保留")
    lock = LockedFragmentSnapshot(id=uuid4(), text="必须保留", order_index=0)
    selected = [SelectedSuggestion(suggestion=suggestion(0), note="语气温和")]
    provider = FakeProvider([result("新稿仍然包含必须保留")])

    output = await service(provider).regenerate_from_suggestions(
        task(TaskState.EDITING, has_first_draft=True),
        parent,
        analysis(),
        selected,
        "保持克制",
        [lock],
        provider_config(),
        "model-id",
    )

    assert output.kind == VersionKind.AI_REVISION
    assert output.parent_version_id == parent.id
    assert output.state.succeeded == TaskState.EDITING
    assert output.provenance["scope"] == "suggestions"
    assert output.provenance["selected_suggestion_ids"] == ["suggestion-0"]
    assert output.validation_status == ValidationStatus.SATISFIED


@pytest.mark.asyncio
async def test_invalid_transition_fails_before_spending_provider_call() -> None:
    provider = FakeProvider([result("不会调用")])
    with pytest.raises(InvalidTaskTransition):
        await service(provider).analyze(
            task(TaskState.EDITING, has_first_draft=True),
            provider_config(),
            "model-id",
        )
    assert provider.requests == []


@pytest.mark.asyncio
async def test_full_revision_rejects_changed_lock() -> None:
    provider = FakeProvider([result("保留内容被改写")])
    locked = [LockedFragmentSnapshot(id=uuid4(), text="必须保留", order_index=0)]
    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).revise_full(
            task(TaskState.EDITING, has_first_draft=True),
            VersionAiSnapshot(id=uuid4(), content="开头必须保留结尾"),
            "更口语",
            locked,
            provider_config(),
            "model-id",
        )
    assert caught.value.error.code == AiErrorCode.PRESERVATION_FAILED
    assert caught.value.state.failed == TaskState.EDITING
    assert caught.value.error.details["violations"][0]["fragment_id"] == str(locked[0].id)


@pytest.mark.asyncio
async def test_selection_revision_validates_outside_text_and_locks() -> None:
    parent = VersionAiSnapshot(id=uuid4(), content="开头旧内容结尾")
    lock_id = uuid4()
    provider = FakeProvider([result("开头新内容结尾"), result("改了开头新内容结尾")])
    task_snapshot = task(TaskState.EDITING, has_first_draft=True)
    locks = [LockedFragmentSnapshot(id=lock_id, text="开头", order_index=0)]

    valid = await service(provider).revise_selection(
        task_snapshot,
        parent,
        Selection(start=2, end=5),
        "替换",
        locks,
        provider_config(),
        "model-id",
    )
    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).revise_selection(
            task_snapshot,
            parent,
            Selection(start=2, end=5),
            "替换",
            locks,
            provider_config(),
            "model-id",
        )

    assert valid.validation_status == ValidationStatus.SATISFIED
    assert caught.value.error.code == AiErrorCode.PRESERVATION_FAILED


@pytest.mark.asyncio
async def test_finalized_task_can_branch_and_restores_finalized_on_failure() -> None:
    provider = FakeProvider([result("开头新内容结尾")])
    output = await service(provider).revise_selection(
        task(TaskState.FINALIZED, has_first_draft=True),
        VersionAiSnapshot(id=uuid4(), content="开头旧内容结尾"),
        Selection(start=2, end=5),
        "替换",
        [],
        provider_config(),
        "model-id",
    )
    assert output.state.running == TaskState.REVISING
    assert output.state.succeeded == TaskState.EDITING
    assert output.state.failed == TaskState.FINALIZED


@pytest.mark.asyncio
async def test_provider_error_is_wrapped_with_safe_failure_state() -> None:
    provider = FakeProvider([AiError(AiErrorCode.RATE_LIMITED, retryable=True)])
    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).analyze(task(TaskState.DRAFT), provider_config(), "model-id")

    assert caught.value.state.failed == TaskState.DRAFT
    assert caught.value.as_error()["code"] == "provider_rate_limited"
    assert caught.value.as_error()["details"]["retryable"] is True


@pytest.mark.asyncio
async def test_empty_generated_text_does_not_create_a_version_result() -> None:
    provider = FakeProvider([result("  \n")])
    with pytest.raises(AiOperationFailed) as caught:
        await service(provider).create_first_draft(
            task(TaskState.SUGGESTIONS_READY),
            analysis(),
            [],
            provider_config(),
            "model-id",
        )
    assert caught.value.error.code == AiErrorCode.INVALID_RESPONSE
    assert caught.value.error.details == {"reason": "empty_content"}


def test_locks_are_sorted_before_prompting() -> None:
    locks = [
        LockedFragmentSnapshot(id=uuid4(), text="后", order_index=2),
        LockedFragmentSnapshot(id=uuid4(), text="前", order_index=1),
    ]
    converted = [
        LockedFragment(fragment_id=str(item.id), text=item.text)
        for item in sorted(locks, key=lambda item: item.order_index)
    ]
    assert [item.text for item in converted] == ["前", "后"]
