from uuid import uuid4

import pytest

from app.modules.tasks.domain import (
    FirstDraftAlreadyExists,
    InvalidTaskTransition,
    LockConstraint,
    TaskState,
    VersionKind,
    assert_transition,
    validate_lock_constraints,
)
from app.modules.tasks.service import (
    TaskDomainService,
    TaskSnapshot,
    assert_no_overlapping_range,
    assert_owned,
    selected_text,
)


def test_task_state_machine_rejects_skipping_analysis() -> None:
    with pytest.raises(InvalidTaskTransition):
        assert_transition(TaskState.DRAFT, TaskState.GENERATING)


def test_task_can_be_archived_and_restored() -> None:
    task = TaskSnapshot(id=uuid4(), owner_id=uuid4(), state=TaskState.ANALYSIS_READY)
    service = TaskDomainService()

    service.archive(task)
    assert task.state == TaskState.ARCHIVED
    service.restore(task)

    assert task.state == TaskState.ANALYSIS_READY
    assert task.archived_from_state is None


def test_task_accepts_only_one_first_draft() -> None:
    task = TaskSnapshot(id=uuid4(), owner_id=uuid4(), state=TaskState.GENERATING)
    service = TaskDomainService()

    service.register_first_draft(task)
    task.state = TaskState.GENERATING

    with pytest.raises(FirstDraftAlreadyExists):
        service.register_first_draft(task)


def test_revision_requires_first_draft() -> None:
    task = TaskSnapshot(id=uuid4(), owner_id=uuid4(), state=TaskState.EDITING)

    with pytest.raises(ValueError, match="existing first draft"):
        TaskDomainService().register_revision(task, VersionKind.MANUAL_EDIT)


def test_lock_validation_preserves_exact_text_and_order() -> None:
    locks = [LockConstraint("first", 0), LockConstraint("third", 1)]

    assert validate_lock_constraints("first second third", locks) == []
    assert validate_lock_constraints("third then first", locks) == []


def test_selection_and_overlap_validation() -> None:
    assert selected_text("abcdef", 1, 4) == "bcd"
    assert_no_overlapping_range(4, 6, [(0, 4)])

    with pytest.raises(ValueError, match="overlap"):
        assert_no_overlapping_range(3, 6, [(0, 4)])


def test_member_cannot_access_another_members_resource() -> None:
    with pytest.raises(PermissionError):
        assert_owned(uuid4(), uuid4())
