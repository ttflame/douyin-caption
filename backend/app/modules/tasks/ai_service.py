"""Application bridge between task state and the provider-neutral AI module."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.modules.ai.dto import (
    Analysis,
    AnalysisInput,
    AnalysisResult,
    CompletionRequest,
    CompletionResult,
    FirstDraftInput,
    FullRevisionInput,
    ProviderUsage,
    SelectedSuggestion,
    Selection,
    SelectionRevisionInput,
    Suggestion,
    SuggestionSet,
    SuggestionsInput,
    TextAnalysis,
    ValidationResult,
)
from app.modules.ai.dto import (
    CreativeSettings as AiCreativeSettings,
)
from app.modules.ai.dto import (
    LockedFragment as AiLockedFragment,
)
from app.modules.ai.errors import AiError, AiErrorCode
from app.modules.ai.parsing import parse_structured_output
from app.modules.ai.provider import OpenAICompatibleProvider, Provider, ProviderConfig
from app.modules.ai.validation import (
    analysis_reference_ids,
    validate_locked_fragments,
    validate_selection_revision,
    validate_suggestion_references,
)
from app.modules.ai.workflow import AiWorkflow
from app.modules.tasks.domain import (
    FirstDraftAlreadyExists,
    TaskState,
    ValidationStatus,
    VersionKind,
    assert_transition,
)
from app.modules.tasks.schemas import CreativeSettings

PROMPT_TEMPLATE_VERSION = "ai-workflow-v4"


@dataclass(frozen=True, slots=True)
class TaskAiSnapshot:
    """Only the task data needed by an AI operation."""

    id: UUID
    state: TaskState
    source_text: str
    creative_settings: CreativeSettings
    has_first_draft: bool


@dataclass(frozen=True, slots=True)
class VersionAiSnapshot:
    id: UUID
    content: str


@dataclass(frozen=True, slots=True)
class LockedFragmentSnapshot:
    id: UUID
    text: str
    order_index: int


@dataclass(frozen=True, slots=True)
class StatePlan:
    initial: TaskState
    running: TaskState
    succeeded: TaskState
    failed: TaskState


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    model_identifier: str
    prompt_template_version: str
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class AnalysisServiceResult:
    state: StatePlan
    analysis: TextAnalysis
    metadata: ProviderMetadata


@dataclass(frozen=True, slots=True)
class SuggestionsServiceResult:
    state: StatePlan
    suggestions: SuggestionSet
    metadata: ProviderMetadata


@dataclass(frozen=True, slots=True)
class VersionServiceResult:
    state: StatePlan
    parent_version_id: UUID | None
    kind: VersionKind
    content: str
    instruction: str | None
    validation_status: ValidationStatus
    validation: ValidationResult
    provenance: dict[str, Any]
    metadata: ProviderMetadata


class AiOperationFailed(RuntimeError):
    """Safe provider failure plus the state that persistence must restore."""

    def __init__(self, state: StatePlan, error: AiError) -> None:
        self.state = state
        self.error = error
        super().__init__(error.message)

    def as_error(self) -> dict[str, Any]:
        return self.error.as_dict()


ProviderFactory = Callable[[ProviderConfig], Provider]


class TaskAiService:
    """Runs AI calls while leaving all persistence decisions to the caller."""

    def __init__(
        self,
        workflow: AiWorkflow | None = None,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._workflow = workflow or AiWorkflow()
        self._provider_factory = provider_factory or OpenAICompatibleProvider

    async def analyze(
        self,
        task: TaskAiSnapshot,
        provider_config: ProviderConfig,
        model_identifier: str,
    ) -> AnalysisServiceResult:
        plan = _state_plan(
            task.state,
            running=TaskState.ANALYZING,
            succeeded=TaskState.ANALYSIS_READY,
        )
        request = self._workflow.analysis_request(
            model_identifier,
            AnalysisInput(source_text=task.source_text),
        )
        response = await self._complete(provider_config, request, plan)
        _require_nonempty_text(response, plan)
        analysis = TextAnalysis(content=response.text)
        return AnalysisServiceResult(plan, analysis, _metadata(model_identifier, response))

    async def suggest(
        self,
        task: TaskAiSnapshot,
        analysis: AnalysisResult,
        provider_config: ProviderConfig,
        model_identifier: str,
        *,
        member_context: str = "",
        previous_suggestions: list[Suggestion] | None = None,
        fixed_suggestions: list[SelectedSuggestion] | None = None,
    ) -> SuggestionsServiceResult:
        plan = _state_plan(
            task.state,
            running=TaskState.SUGGESTING,
            succeeded=TaskState.SUGGESTIONS_READY,
        )
        request = self._workflow.suggestions_request(
            model_identifier,
            SuggestionsInput(
                source_text=task.source_text,
                settings=_to_ai_settings(task.creative_settings),
                analysis=analysis,
                member_context=member_context,
                previous_suggestions=previous_suggestions or [],
                fixed_suggestions=fixed_suggestions or [],
            ),
        )
        response = await self._complete(provider_config, request, plan)
        suggestions = _parse(response, SuggestionSet, plan)
        if not validate_suggestion_references(analysis, suggestions):
            raise AiOperationFailed(
                plan,
                AiError(
                    AiErrorCode.INVALID_RESPONSE,
                    retryable=True,
                    details={"reason": "unknown_analysis_issue"},
                ),
            )
        return SuggestionsServiceResult(plan, suggestions, _metadata(model_identifier, response))

    async def create_first_draft(
        self,
        task: TaskAiSnapshot,
        analysis: AnalysisResult,
        selected_suggestions: list[SelectedSuggestion],
        provider_config: ProviderConfig,
        model_identifier: str,
        *,
        member_requirements: str = "",
    ) -> VersionServiceResult:
        if task.has_first_draft:
            raise FirstDraftAlreadyExists("A task can have only one first draft")
        plan = _state_plan(
            task.state,
            running=TaskState.GENERATING,
            succeeded=TaskState.EDITING,
        )
        _assert_selected_suggestions_reference_analysis(analysis, selected_suggestions)
        request = self._workflow.first_draft_request(
            model_identifier,
            FirstDraftInput(
                source_text=task.source_text,
                settings=_to_ai_settings(task.creative_settings),
                analysis=analysis,
                selected_suggestions=selected_suggestions,
                member_requirements=member_requirements,
            ),
        )
        response = await self._complete(provider_config, request, plan)
        _require_nonempty_text(response, plan)
        return VersionServiceResult(
            state=plan,
            parent_version_id=None,
            kind=VersionKind.FIRST_DRAFT,
            content=response.text,
            instruction=member_requirements or None,
            validation_status=ValidationStatus.NOT_CHECKED,
            validation=ValidationResult(valid=True),
            provenance={
                "analysis_issue_ids": (
                    analysis.conclusion.key_issue_ids
                    if isinstance(analysis, Analysis)
                    else ["analysis"]
                ),
                "selected_suggestion_ids": [
                    item.suggestion.suggestion_id for item in selected_suggestions
                ],
            },
            metadata=_metadata(model_identifier, response),
        )

    async def revise_full(
        self,
        task: TaskAiSnapshot,
        parent: VersionAiSnapshot,
        instruction: str,
        locked_fragments: list[LockedFragmentSnapshot],
        provider_config: ProviderConfig,
        model_identifier: str,
    ) -> VersionServiceResult:
        plan = self._revision_plan(task)
        ordered_locks = _to_ai_locks(locked_fragments)
        request = self._workflow.full_revision_request(
            model_identifier,
            FullRevisionInput(
                parent_text=parent.content,
                instruction=instruction,
                settings=_to_ai_settings(task.creative_settings),
                locked_fragments=ordered_locks,
            ),
        )
        response = await self._complete(provider_config, request, plan)
        _require_nonempty_text(response, plan)
        validation = validate_locked_fragments(response.text, ordered_locks)
        return _revision_result(
            plan,
            parent,
            instruction,
            response,
            validation,
            model_identifier,
            scope="full",
            locked_fragment_ids=[item.id for item in locked_fragments],
        )

    async def revise_selection(
        self,
        task: TaskAiSnapshot,
        parent: VersionAiSnapshot,
        selection: Selection,
        instruction: str,
        locked_fragments: list[LockedFragmentSnapshot],
        provider_config: ProviderConfig,
        model_identifier: str,
    ) -> VersionServiceResult:
        plan = self._revision_plan(task)
        ordered_locks = _to_ai_locks(locked_fragments)
        revision_input = SelectionRevisionInput(
            parent_text=parent.content,
            instruction=instruction,
            settings=_to_ai_settings(task.creative_settings),
            locked_fragments=ordered_locks,
            selection=selection,
        )
        request = self._workflow.selection_revision_request(model_identifier, revision_input)
        response = await self._complete(provider_config, request, plan)
        _require_nonempty_text(response, plan)
        validation = validate_selection_revision(
            parent.content,
            response.text,
            selection,
            ordered_locks,
        )
        return _revision_result(
            plan,
            parent,
            instruction,
            response,
            validation,
            model_identifier,
            scope="selection",
            selection=selection,
            locked_fragment_ids=[item.id for item in locked_fragments],
        )

    @staticmethod
    def _revision_plan(task: TaskAiSnapshot) -> StatePlan:
        if not task.has_first_draft:
            raise ValueError("A revision requires an existing first draft")
        return _state_plan(
            task.state,
            running=TaskState.REVISING,
            succeeded=TaskState.EDITING,
        )

    async def _complete(
        self, config: ProviderConfig, request: CompletionRequest, plan: StatePlan
    ) -> CompletionResult:
        try:
            return await self._provider_factory(config).complete(request)
        except AiError as error:
            raise AiOperationFailed(plan, error) from error


def _state_plan(initial: TaskState, *, running: TaskState, succeeded: TaskState) -> StatePlan:
    assert_transition(initial, running)
    assert_transition(running, succeeded)
    return StatePlan(initial=initial, running=running, succeeded=succeeded, failed=initial)


def _to_ai_settings(settings: CreativeSettings) -> AiCreativeSettings:
    return AiCreativeSettings(
        target_length_mode=settings.target_length_mode,
        target_character_count=settings.target_characters,
        persona=settings.persona.model_dump_json(),
        audience=settings.audience.model_dump_json(),
        language_style=settings.language_style.model_dump_json(),
        content_structure=settings.content_structure.model_dump_json(),
        output_specification=settings.output_specification.model_dump_json(),
        hard_constraints=settings.hard_constraints.model_dump_json(),
    )


def _to_ai_locks(locks: list[LockedFragmentSnapshot]) -> list[AiLockedFragment]:
    return [
        AiLockedFragment(fragment_id=str(item.id), text=item.text)
        for item in sorted(locks, key=lambda item: item.order_index)
    ]


def _parse[OutputType: BaseModel](
    response: CompletionResult,
    output_type: type[OutputType],
    plan: StatePlan,
) -> OutputType:
    try:
        return parse_structured_output(response.text, output_type)
    except AiError as error:
        raise AiOperationFailed(plan, error) from error


def _metadata(model_identifier: str, response: CompletionResult) -> ProviderMetadata:
    usage: ProviderUsage = response.usage
    return ProviderMetadata(
        model_identifier=model_identifier,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        provider_request_id=response.provider_request_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )


def _require_nonempty_text(response: CompletionResult, plan: StatePlan) -> None:
    if not response.text.strip():
        raise AiOperationFailed(
            plan,
            AiError(
                AiErrorCode.INVALID_RESPONSE,
                retryable=True,
                details={"reason": "empty_content"},
            ),
        )


def _assert_selected_suggestions_reference_analysis(
    analysis: AnalysisResult, selected_suggestions: list[SelectedSuggestion]
) -> None:
    issue_ids = analysis_reference_ids(analysis)
    suggestion_ids = [item.suggestion.suggestion_id for item in selected_suggestions]
    if len(suggestion_ids) != len(set(suggestion_ids)):
        raise ValueError("Selected suggestion identifiers must be unique")
    if any(
        not set(item.suggestion.analysis_issue_ids).issubset(issue_ids)
        for item in selected_suggestions
    ):
        raise ValueError("A selected suggestion references an unknown analysis issue")


def _revision_result(
    plan: StatePlan,
    parent: VersionAiSnapshot,
    instruction: str,
    response: CompletionResult,
    validation: ValidationResult,
    model_identifier: str,
    *,
    scope: str,
    locked_fragment_ids: list[UUID],
    selection: Selection | None = None,
) -> VersionServiceResult:
    if not validation.valid:
        raise AiOperationFailed(
            plan,
            AiError(
                AiErrorCode.PRESERVATION_FAILED,
                retryable=True,
                details=validation.model_dump(mode="json"),
            ),
        )
    provenance: dict[str, Any] = {
        "scope": scope,
        "locked_fragment_ids": [str(item) for item in locked_fragment_ids],
    }
    if selection is not None:
        provenance["selection"] = selection.model_dump()
    return VersionServiceResult(
        state=plan,
        parent_version_id=parent.id,
        kind=VersionKind.AI_REVISION,
        content=response.text,
        instruction=instruction,
        validation_status=ValidationStatus.SATISFIED,
        validation=validation,
        provenance=provenance,
        metadata=_metadata(model_identifier, response),
    )
