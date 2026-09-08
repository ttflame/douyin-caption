from dataclasses import dataclass
from enum import StrEnum


class TaskState(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    ANALYSIS_READY = "analysis_ready"
    SUGGESTING = "suggesting"
    SUGGESTIONS_READY = "suggestions_ready"
    GENERATING = "generating"
    EDITING = "editing"
    REVISING = "revising"
    FINALIZED = "finalized"
    ARCHIVED = "archived"


class VersionKind(StrEnum):
    FIRST_DRAFT = "first_draft"
    AI_REVISION = "ai_revision"
    MANUAL_EDIT = "manual_edit"


class ValidationStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    SATISFIED = "satisfied"
    FAILED = "failed"


class SuggestionPriority(StrEnum):
    PRIMARY = "primary"
    OPTIONAL = "optional"


class SuggestionDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class AiOperationKind(StrEnum):
    ANALYSIS = "analysis"
    SUGGESTIONS = "suggestions"
    FIRST_DRAFT = "first_draft"
    REVISION = "revision"


class AiOperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTaskTransition(ValueError):
    pass


class FirstDraftAlreadyExists(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.DRAFT: frozenset({TaskState.ANALYZING}),
    TaskState.ANALYZING: frozenset({TaskState.ANALYSIS_READY, TaskState.DRAFT}),
    TaskState.ANALYSIS_READY: frozenset({TaskState.ANALYZING, TaskState.SUGGESTING}),
    TaskState.SUGGESTING: frozenset({TaskState.SUGGESTIONS_READY, TaskState.ANALYSIS_READY}),
    TaskState.SUGGESTIONS_READY: frozenset({TaskState.SUGGESTING, TaskState.GENERATING}),
    TaskState.GENERATING: frozenset({TaskState.EDITING, TaskState.SUGGESTIONS_READY}),
    TaskState.EDITING: frozenset({TaskState.REVISING, TaskState.FINALIZED}),
    TaskState.REVISING: frozenset({TaskState.EDITING}),
    TaskState.FINALIZED: frozenset({TaskState.REVISING}),
    TaskState.ARCHIVED: frozenset(),
}


def assert_transition(current: TaskState, target: TaskState) -> None:
    if target == TaskState.ARCHIVED and current != TaskState.ARCHIVED:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransition(f"Cannot transition task from {current} to {target}")


@dataclass(frozen=True, slots=True)
class LockConstraint:
    text: str
    order_index: int


def validate_lock_constraints(content: str, locks: list[LockConstraint]) -> list[str]:
    """Return missing lock texts, including missing repeated occurrences."""
    cursors: dict[str, int] = {}
    failures: list[str] = []
    for lock in sorted(locks, key=lambda item: item.order_index):
        position = content.find(lock.text, cursors.get(lock.text, 0))
        if position < 0:
            failures.append(lock.text)
            continue
        cursors[lock.text] = position + len(lock.text)
    return failures
