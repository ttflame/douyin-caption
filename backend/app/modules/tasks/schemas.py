from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.ai.dto import AnalysisResult
from app.modules.tasks.domain import (
    AiOperationKind,
    AiOperationStatus,
    SuggestionDecision,
    SuggestionPriority,
    TaskState,
    ValidationStatus,
    VersionKind,
)

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PersonaSettings(BaseModel):
    account_positioning: str = ""
    speaker_identity: str = ""
    professional_background: str = ""
    audience_relationship: str = ""
    stance: str = ""
    custom_instruction: str = ""


class AudienceSettings(BaseModel):
    target_audience: str = ""
    pain_points: list[str] = []
    awareness_level: str = ""
    desired_action: str = ""
    custom_instruction: str = ""


class LanguageStyleSettings(BaseModel):
    preset: str = "natural_spoken"
    colloquial_level: int = Field(default=3, ge=1, le=5)
    emotion_level: int = Field(default=3, ge=1, le=5)
    rhythm: str = "balanced"
    sentence_length: str = "mixed"
    tone: str = "direct"
    allow_internet_slang: bool = False
    custom_instruction: str = ""


class ContentStructureSettings(BaseModel):
    opening: str = "problem_hook"
    narrative: str = "progressive"
    conflict_level: int = Field(default=2, ge=1, le=5)
    require_example: bool = False
    call_to_action: str = ""
    custom_instruction: str = ""


class OutputSpecification(BaseModel):
    preserve_paragraphs: bool = True
    preserve_pauses: bool = False
    custom_instruction: str = ""


class HardConstraints(BaseModel):
    required_information: list[str] = []
    forbidden_expressions: list[str] = []
    immutable_facts: list[str] = []
    platform_safety_instruction: str = ""
    custom_instruction: str = ""


class CreativeSettings(BaseModel):
    target_length_mode: Literal["fixed", "follow_source"] = "fixed"
    target_characters: int = Field(ge=1, le=20_000)
    persona: PersonaSettings = PersonaSettings()
    audience: AudienceSettings = AudienceSettings()
    language_style: LanguageStyleSettings = LanguageStyleSettings()
    content_structure: ContentStructureSettings = ContentStructureSettings()
    output_specification: OutputSpecification = OutputSpecification()
    hard_constraints: HardConstraints = HardConstraints()


class TaskCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    source_text: NonBlankText
    creative_settings: CreativeSettings

    @model_validator(mode="after")
    def validate_source_length(self) -> "TaskCreate":
        if len(self.source_text) > 20_000:
            raise ValueError("Source text cannot exceed 20,000 characters")
        return self


class TaskUpdate(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ] = None
    source_text: str | None = Field(default=None, min_length=1, max_length=20_000)
    creative_settings: CreativeSettings | None = None


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None


class TaskDetail(TaskSummary):
    source_text: str
    creative_settings: CreativeSettings


class PresetCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    settings: CreativeSettings


class PresetUpdate(BaseModel):
    name: Annotated[
        str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ] = None
    settings: CreativeSettings | None = None


class PresetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    settings: CreativeSettings
    created_at: datetime
    updated_at: datetime


class SuggestionUpdate(BaseModel):
    decision: SuggestionDecision
    member_note: str | None = Field(default=None, max_length=2_000)


class SuggestionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    analysis_id: UUID
    suggestion_key: str
    analysis_issue_ids: list[str]
    priority: SuggestionPriority
    title: str
    problem: str
    direction: str
    reason: str
    impact_scope: str
    example: str | None
    decision: SuggestionDecision
    member_note: str | None


class AnalysisSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisCorrection(BaseModel):
    analysis: AnalysisResult
    member_notes: str | None = Field(default=None, max_length=4_000)


class AnalysisView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence: int
    payload: dict[str, Any]
    member_notes: str | None
    is_selected: bool
    prompt_template_version: str
    model_identifier: str
    created_at: datetime


class SuggestionsSubmit(BaseModel):
    analysis_id: UUID | None = None
    member_context: str = Field(default="", max_length=4_000)


class FirstDraftSubmit(BaseModel):
    analysis_id: UUID | None = None
    member_requirements: str = Field(default="", max_length=4_000)


class RevisionSubmit(BaseModel):
    parent_version_id: UUID
    scope: str = Field(pattern="^(full|selection)$")
    instruction: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)
    ]
    selection_start: int | None = Field(default=None, ge=0)
    selection_end: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_selection(self) -> "RevisionSubmit":
        if self.scope == "selection":
            if self.selection_start is None or self.selection_end is None:
                raise ValueError("Selection offsets are required for a selection revision")
            if self.selection_end <= self.selection_start:
                raise ValueError("Selection end must be after its start")
        elif self.selection_start is not None or self.selection_end is not None:
            raise ValueError("Selection offsets are only valid for a selection revision")
        return self


class AiOperationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    task_name: str
    kind: AiOperationKind
    status: AiOperationStatus
    resource_type: str | None
    resource_id: UUID | None
    error_code: str | None
    error_message: str | None
    error_details: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ManualEditCreate(BaseModel):
    content: NonBlankText
    instruction: str | None = Field(default=None, max_length=2_000)


class LockedFragmentCreate(BaseModel):
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_range(self) -> "LockedFragmentCreate":
        if self.end_offset <= self.start_offset:
            raise ValueError("Selection end must be after its start")
        return self


class LockedFragmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_version_id: UUID
    text: str
    start_offset: int
    end_offset: int
    order_index: int
    note: str | None


class VersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    kind: VersionKind
    content: str
    instruction: str | None
    provenance: dict[str, Any]
    validation_status: ValidationStatus
    validation_details: dict[str, Any]
    is_current_final: bool
    created_at: datetime
