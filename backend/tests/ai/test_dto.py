import pytest
from pydantic import ValidationError

from app.modules.ai.dto import Analysis, Selection, Suggestion, SuggestionSet


def suggestion(index: int) -> Suggestion:
    return Suggestion(
        suggestion_id=f"s-{index}",
        priority="primary" if index == 0 else "optional",
        title="压缩开头",
        analysis_issue_ids=["issue-1"],
        problem="开头重复",
        direction="删除重复句",
        rationale="更快进入主题",
        impact_scope="开头",
        example="直接说结论",
    )


@pytest.mark.parametrize("count", [5, 6, 8])
def test_suggestion_count_accepts_product_range(count: int) -> None:
    suggestion_set = SuggestionSet(suggestions=[suggestion(i) for i in range(count)])
    assert len(suggestion_set.suggestions) == count


@pytest.mark.parametrize("count", [4, 9])
def test_suggestion_count_rejects_outside_product_range(count: int) -> None:
    with pytest.raises(ValidationError):
        SuggestionSet(suggestions=[suggestion(i) for i in range(count)])


def test_selection_requires_ordered_nonempty_range() -> None:
    with pytest.raises(ValidationError):
        Selection(start=3, end=3)


def test_structured_schemas_are_compatible_with_openai_strict_mode() -> None:
    for model in (Analysis, SuggestionSet):
        schema = model.model_json_schema()
        object_schemas = [schema, *schema.get("$defs", {}).values()]
        for item in object_schemas:
            if item.get("type") == "object":
                assert item.get("additionalProperties") is False
                assert set(item.get("required", [])) == set(item.get("properties", {}))


def test_suggestion_identifiers_must_be_unique() -> None:
    duplicate = suggestion(0)
    with pytest.raises(ValidationError):
        SuggestionSet(suggestions=[duplicate] * 5)
