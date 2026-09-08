from dataclasses import dataclass, field
from uuid import UUID

from app.modules.tasks.domain import (
    FirstDraftAlreadyExists,
    TaskState,
    VersionKind,
    assert_transition,
)


@dataclass(slots=True)
class TaskSnapshot:
    id: UUID
    owner_id: UUID
    state: TaskState = TaskState.DRAFT
    archived_from_state: TaskState | None = None
    version_kinds: list[VersionKind] = field(default_factory=list)


class TaskDomainService:
    """Enforces workflow invariants independently of HTTP and persistence."""

    def transition(self, task: TaskSnapshot, target: TaskState) -> None:
        assert_transition(task.state, target)
        task.state = target

    def archive(self, task: TaskSnapshot) -> None:
        if task.state == TaskState.ARCHIVED:
            return
        task.archived_from_state = task.state
        task.state = TaskState.ARCHIVED

    def restore(self, task: TaskSnapshot) -> None:
        if task.state != TaskState.ARCHIVED or task.archived_from_state is None:
            raise ValueError("Only an archived task with a previous state can be restored")
        task.state = task.archived_from_state
        task.archived_from_state = None

    def register_first_draft(self, task: TaskSnapshot) -> None:
        if VersionKind.FIRST_DRAFT in task.version_kinds:
            raise FirstDraftAlreadyExists("A task can have only one first draft")
        assert_transition(task.state, TaskState.EDITING)
        task.version_kinds.append(VersionKind.FIRST_DRAFT)
        task.state = TaskState.EDITING

    def register_revision(self, task: TaskSnapshot, kind: VersionKind) -> None:
        if kind == VersionKind.FIRST_DRAFT:
            raise ValueError("Use register_first_draft for a first draft")
        if VersionKind.FIRST_DRAFT not in task.version_kinds:
            raise ValueError("A revision requires an existing first draft")
        task.version_kinds.append(kind)


def assert_owned(resource_owner_id: UUID, actor_id: UUID) -> None:
    if resource_owner_id != actor_id:
        raise PermissionError("Resource does not belong to the authenticated member")


def selected_text(content: str, start_offset: int, end_offset: int) -> str:
    if start_offset < 0 or end_offset <= start_offset or end_offset > len(content):
        raise ValueError("Selection is outside the source version")
    return content[start_offset:end_offset]


def assert_no_overlapping_range(
    start_offset: int,
    end_offset: int,
    existing_ranges: list[tuple[int, int]],
) -> None:
    if any(
        start_offset < existing_end and end_offset > existing_start
        for existing_start, existing_end in existing_ranges
    ):
        raise ValueError("Locked fragments cannot overlap")
