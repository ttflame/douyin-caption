from app.modules.ai.dto import LockedFragment, Selection, Suggestion, SuggestionSet
from app.modules.ai.validation import (
    validate_locked_fragments,
    validate_selection_revision,
    validate_suggestion_references,
)


def test_locked_fragments_must_be_exact_but_can_move() -> None:
    locks = [
        LockedFragment(fragment_id="a", text="第一段"),
        LockedFragment(fragment_id="b", text="第二段"),
    ]
    assert validate_locked_fragments("开场 第一段 中间 第二段 结尾", locks).valid

    changed = validate_locked_fragments("第一端改了，第二段", locks)
    assert not changed.valid
    assert changed.violations[0].code == "missing_fragment"

    reordered = validate_locked_fragments("第二段，然后第一段", locks)
    assert reordered.valid


def test_repeated_locked_sentences_require_matching_occurrences() -> None:
    locks = [LockedFragment(fragment_id=str(i), text="保留。") for i in range(2)]
    assert validate_locked_fragments("保留。新内容。保留。", locks).valid
    assert not validate_locked_fragments("保留。新内容。", locks).valid


def test_selection_revision_requires_both_outside_regions_unchanged() -> None:
    parent = "固定开头旧内容固定结尾"
    selection = Selection(start=4, end=7)
    assert validate_selection_revision(parent, "固定开头新内容固定结尾", selection, []).valid

    result = validate_selection_revision(parent, "改动开头新内容固定结尾", selection, [])
    assert not result.valid
    assert result.violations[0].code == "selection_outside_changed"


def test_selection_validation_rejects_overlapping_prefix_and_suffix_match() -> None:
    parent = "abcXabc"
    result = validate_selection_revision(parent, "abc", Selection(start=3, end=4), [])
    assert not result.valid


def test_selection_revision_also_checks_locks() -> None:
    result = validate_selection_revision(
        "头部中间尾部",
        "头部替换尾部",
        Selection(start=2, end=4),
        [LockedFragment(fragment_id="locked", text="中间")],
    )
    assert not result.valid
    assert any(item.code == "missing_fragment" for item in result.violations)


def test_suggestions_must_reference_selected_analysis(analysis) -> None:
    def make_suggestion(issue_id: str, index: int) -> Suggestion:
        return Suggestion(
            suggestion_id=f"s-{index}",
            priority="optional",
            title="建议",
            analysis_issue_ids=[issue_id],
            problem="问题",
            direction="方向",
            rationale="理由",
            impact_scope="主体",
            example="示例",
        )

    valid = SuggestionSet(suggestions=[make_suggestion("issue-1", i) for i in range(5)])
    invalid = SuggestionSet(
        suggestions=[make_suggestion("missing" if i == 0 else "issue-1", i) for i in range(5)]
    )
    assert validate_suggestion_references(analysis, valid)
    assert not validate_suggestion_references(analysis, invalid)
