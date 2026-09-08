import json

import pytest

from app.modules.ai.dto import SuggestionSet
from app.modules.ai.errors import AiError, AiErrorCode
from app.modules.ai.parsing import parse_structured_output


def test_parse_structured_output_returns_validated_dto() -> None:
    item = {
        "suggestion_id": "s-1",
        "priority": "primary",
        "title": "压缩",
        "analysis_issue_ids": ["issue-1"],
        "problem": "重复",
        "direction": "删除",
        "rationale": "提高节奏",
        "impact_scope": "开头",
        "example": "直接说结论",
    }
    value = parse_structured_output(
        json.dumps({"suggestions": [{**item, "suggestion_id": f"s-{i}"} for i in range(5)]}),
        SuggestionSet,
    )
    assert len(value.suggestions) == 5


def test_parse_structured_output_normalizes_invalid_json() -> None:
    with pytest.raises(AiError) as caught:
        parse_structured_output("not json", SuggestionSet)
    assert caught.value.code == AiErrorCode.INVALID_RESPONSE
