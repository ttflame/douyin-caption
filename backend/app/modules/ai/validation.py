"""Deterministic validation of exact preservation constraints."""

from .dto import (
    AnalysisResult,
    LockedFragment,
    Selection,
    SuggestionSet,
    TextAnalysis,
    ValidationResult,
    ValidationViolation,
)


def validate_locked_fragments(
    candidate: str, locked_fragments: list[LockedFragment]
) -> ValidationResult:
    violations: list[ValidationViolation] = []
    cursors: dict[str, int] = {}
    for fragment in locked_fragments:
        position = candidate.find(fragment.text, cursors.get(fragment.text, 0))
        if position >= 0:
            cursors[fragment.text] = position + len(fragment.text)
            continue
        violations.append(
            ValidationViolation(
                code="missing_fragment",
                fragment_id=fragment.fragment_id,
                message="保留片段缺失、已被修改或重复次数不足。",
            )
        )
    return ValidationResult(valid=not violations, violations=violations)


def analysis_reference_ids(analysis: AnalysisResult) -> set[str]:
    if isinstance(analysis, TextAnalysis):
        return {"analysis"}
    return {issue.issue_id for issue in analysis.problems_and_risks}


def validate_suggestion_references(analysis: AnalysisResult, suggestions: SuggestionSet) -> bool:
    """Return whether every suggestion references an issue in the selected analysis."""
    issue_ids = analysis_reference_ids(analysis)
    return all(
        set(suggestion.analysis_issue_ids).issubset(issue_ids)
        for suggestion in suggestions.suggestions
    )


def validate_selection_revision(
    parent_text: str,
    candidate: str,
    selection: Selection,
    locked_fragments: list[LockedFragment],
) -> ValidationResult:
    prefix = parent_text[: selection.start]
    suffix = parent_text[selection.end :]
    outside_unchanged = (
        len(candidate) >= len(prefix) + len(suffix)
        and candidate.startswith(prefix)
        and candidate.endswith(suffix)
    )
    violations: list[ValidationViolation] = []
    if not outside_unchanged:
        violations.append(
            ValidationViolation(
                code="selection_outside_changed",
                message="选区之外的文字发生了变化。",
            )
        )
    lock_result = validate_locked_fragments(candidate, locked_fragments)
    violations.extend(lock_result.violations)
    return ValidationResult(valid=not violations, violations=violations)
