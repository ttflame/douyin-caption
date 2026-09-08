import pytest

from app.modules.ai.dto import (
    Analysis,
    AnalysisConclusion,
    ContentHighlight,
    ContentOverview,
    CreativeSettings,
    ExpressionAnalysis,
    ParagraphFinding,
    RiskIssue,
    StructureMap,
    StructureSegment,
)


@pytest.fixture
def settings() -> CreativeSettings:
    return CreativeSettings(
        target_character_count=500,
        persona="创业者",
        audience="刚开始做短视频的人",
        language_style="自然口语",
        content_structure="开头直接提出冲突",
        output_specification="短句分段",
        hard_constraints="不得虚构数据",
    )


@pytest.fixture
def analysis() -> Analysis:
    return Analysis(
        content_overview=ContentOverview(
            theme="短视频表达",
            core_viewpoint="先讲清观点",
            target_audience="新手",
            expected_action="开始修改文案",
        ),
        structure_map=StructureMap(
            segments=[
                StructureSegment(
                    segment_id="seg-1",
                    kind="主体",
                    source_excerpt="先讲清观点",
                    purpose="表达主张",
                )
            ]
        ),
        paragraph_analysis=[
            ParagraphFinding(segment_id="seg-1", relationship="独立主体段", issues=["重复"])
        ],
        expression_analysis=ExpressionAnalysis(
            persona_consistency="一致",
            language_style="自然",
            spoken_fluency="流畅",
            emotional_intensity="适中",
            information_density="偏低",
            spoken_rhythm="稳定",
        ),
        content_highlights=[ContentHighlight(excerpt="先讲清观点", reason="核心清楚")],
        problems_and_risks=[
            RiskIssue(
                issue_id="issue-1",
                category="repetition",
                description="信息重复",
                source_excerpt="重复内容",
            )
        ],
        conclusion=AnalysisConclusion(summary="需要压缩重复内容", key_issue_ids=["issue-1"]),
    )
