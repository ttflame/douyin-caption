"""Stable input and output contracts for the AI module."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonBlank = Annotated[str, Field(min_length=1)]


class FrozenDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreativeSettings(FrozenDto):
    target_length_mode: Literal["fixed", "follow_source"] = "fixed"
    target_character_count: int = Field(ge=1, le=20_000)
    persona: str = ""
    audience: str = ""
    language_style: str = ""
    content_structure: str = ""
    output_specification: str = ""
    hard_constraints: str = ""


class ContentOverview(FrozenDto):
    theme: NonBlank
    core_viewpoint: NonBlank
    target_audience: NonBlank
    expected_action: NonBlank


class StructureSegment(FrozenDto):
    segment_id: NonBlank
    kind: NonBlank
    source_excerpt: NonBlank
    purpose: NonBlank


class StructureMap(FrozenDto):
    segments: list[StructureSegment]


class ParagraphFinding(FrozenDto):
    segment_id: NonBlank
    relationship: NonBlank
    issues: list[str]


class ExpressionAnalysis(FrozenDto):
    persona_consistency: NonBlank
    language_style: NonBlank
    spoken_fluency: NonBlank
    emotional_intensity: NonBlank
    information_density: NonBlank
    spoken_rhythm: NonBlank


class ContentHighlight(FrozenDto):
    excerpt: NonBlank
    reason: NonBlank


class RiskIssue(FrozenDto):
    issue_id: NonBlank
    category: Literal[
        "logic_gap",
        "repetition",
        "information_gap",
        "fact_risk",
        "sensitive_expression",
        "drop_off_risk",
        "other",
    ]
    description: NonBlank
    source_excerpt: str


class AnalysisConclusion(FrozenDto):
    summary: NonBlank
    key_issue_ids: list[str]


class Analysis(FrozenDto):
    content_overview: ContentOverview
    structure_map: StructureMap
    paragraph_analysis: list[ParagraphFinding]
    expression_analysis: ExpressionAnalysis
    content_highlights: list[ContentHighlight]
    problems_and_risks: list[RiskIssue]
    conclusion: AnalysisConclusion

    @model_validator(mode="after")
    def validate_internal_references(self) -> "Analysis":
        segment_ids = [segment.segment_id for segment in self.structure_map.segments]
        issue_ids = [issue.issue_id for issue in self.problems_and_risks]
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("structure segment identifiers must be unique")
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("analysis issue identifiers must be unique")
        if not {item.segment_id for item in self.paragraph_analysis}.issubset(segment_ids):
            raise ValueError("paragraph analysis references an unknown segment")
        if not set(self.conclusion.key_issue_ids).issubset(issue_ids):
            raise ValueError("analysis conclusion references an unknown issue")
        return self


class SuggestionPriority(StrEnum):
    PRIMARY = "primary"
    OPTIONAL = "optional"


class Suggestion(FrozenDto):
    suggestion_id: NonBlank
    priority: SuggestionPriority
    title: NonBlank
    analysis_issue_ids: list[str] = Field(min_length=1)
    problem: NonBlank
    direction: NonBlank
    rationale: NonBlank
    impact_scope: NonBlank
    example: NonBlank


class SuggestionSet(FrozenDto):
    suggestions: list[Suggestion] = Field(min_length=5, max_length=8)

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> "SuggestionSet":
        identifiers = [suggestion.suggestion_id for suggestion in self.suggestions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("suggestion identifiers must be unique")
        return self


class SelectedSuggestion(FrozenDto):
    suggestion: Suggestion
    note: str = ""


class LockedFragment(FrozenDto):
    fragment_id: NonBlank
    text: NonBlank


class Selection(FrozenDto):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "Selection":
        if self.end <= self.start:
            raise ValueError("selection end must be greater than start")
        return self


class TextAnalysis(FrozenDto):
    content: NonBlank


AnalysisResult = Analysis | TextAnalysis


class AnalysisInput(FrozenDto):
    source_text: str = Field(min_length=1, max_length=20_000)


class SuggestionsInput(FrozenDto):
    source_text: str = Field(min_length=1, max_length=20_000)
    settings: CreativeSettings
    analysis: AnalysisResult
    member_context: str = ""
    previous_suggestions: list[Suggestion] = Field(default_factory=list)
    fixed_suggestions: list[SelectedSuggestion] = Field(default_factory=list)


class FirstDraftInput(FrozenDto):
    source_text: str = Field(min_length=1, max_length=20_000)
    settings: CreativeSettings
    analysis: AnalysisResult
    selected_suggestions: list[SelectedSuggestion]
    member_requirements: str = ""


class FullRevisionInput(FrozenDto):
    parent_text: NonBlank
    instruction: NonBlank
    settings: CreativeSettings
    locked_fragments: list[LockedFragment] = Field(default_factory=list)


class SelectionRevisionInput(FullRevisionInput):
    selection: Selection

    @model_validator(mode="after")
    def validate_selection_bounds(self) -> "SelectionRevisionInput":
        if self.selection.end > len(self.parent_text):
            raise ValueError("selection is outside parent text")
        return self


class Message(FrozenDto):
    role: Literal["system", "user"]
    content: NonBlank


class CompletionRequest(FrozenDto):
    model: NonBlank
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.4, ge=0, le=2)
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None


class ProviderUsage(FrozenDto):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class CompletionResult(FrozenDto):
    text: str
    provider_request_id: str | None = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class ValidationViolation(FrozenDto):
    code: Literal["missing_fragment", "selection_outside_changed"]
    fragment_id: str | None = None
    message: NonBlank


class ValidationResult(FrozenDto):
    valid: bool
    violations: list[ValidationViolation] = Field(default_factory=list)
