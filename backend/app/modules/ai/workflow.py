"""Pure request construction for each stage of the writing workflow."""

from .dto import (
    AnalysisInput,
    CompletionRequest,
    FirstDraftInput,
    FullRevisionInput,
    Message,
    SelectionRevisionInput,
    SuggestionSet,
    SuggestionsInput,
    TextAnalysis,
)
from .prompts import PromptAssembler, schema_for


class AiWorkflow:
    def __init__(self, prompts: PromptAssembler | None = None) -> None:
        self._prompts = prompts or PromptAssembler()

    def analysis_request(self, model: str, data: AnalysisInput) -> CompletionRequest:
        return CompletionRequest(
            model=model,
            messages=[
                Message(role="system", content="根据原文整理出来一个文案结构，逐条分析"),
                Message(role="user", content=data.source_text),
            ],
        )

    def suggestions_request(self, model: str, data: SuggestionsInput) -> CompletionRequest:
        rule = (
            "基于分析生成 5 至 8 条可独立执行的优化建议，priority 只能为 primary 或 optional。"
            "每条建议必须通过 analysis_issue_ids 引用分析中的问题。"
        )
        if isinstance(data.analysis, TextAnalysis):
            rule += '当前分析为文本，analysis_issue_ids 统一填写 ["analysis"]，引用该分析。'
        if data.previous_suggestions:
            rule += (
                "本轮继续优化已有方案，输出完整的 5 至 8 条建议。"
                "fixed_suggestions 是成员已勾选的固定方案，原样保留其 ID 和所有内容；"
                "只改进未固定的方案，不重复已有固定方案，结合上一轮内容提出更具体的优化方向。"
            )
        schema = schema_for(SuggestionSet)
        return CompletionRequest(
            model=model,
            messages=[
                self._prompts.system_message(data.settings, rule, response_schema=schema),
                self._prompts.user_payload(
                    "请生成优化建议。",
                    source_text=data.source_text,
                    analysis=data.analysis.model_dump(mode="json"),
                    member_context=data.member_context,
                    previous_suggestions=[
                        item.model_dump(mode="json") for item in data.previous_suggestions
                    ],
                    fixed_suggestions=[
                        item.model_dump(mode="json") for item in data.fixed_suggestions
                    ],
                ),
            ],
            response_schema=schema,
            schema_name="douyin_script_suggestions",
        )

    def first_draft_request(self, model: str, data: FirstDraftInput) -> CompletionRequest:
        rule = "根据已采纳建议生成唯一的第一版成品。只返回纯正文，不附解释或标题。"
        return CompletionRequest(
            model=model,
            messages=[
                self._prompts.system_message(data.settings, rule),
                self._prompts.user_payload(
                    "请生成第一版成品。",
                    source_text=data.source_text,
                    analysis=data.analysis.model_dump(mode="json"),
                    selected_suggestions=[
                        item.model_dump(mode="json") for item in data.selected_suggestions
                    ],
                    member_requirements=data.member_requirements,
                ),
            ],
        )

    def full_revision_request(self, model: str, data: FullRevisionInput) -> CompletionRequest:
        rule = (
            "按本轮指令只优化未锁定的文字。locked_fragments 中每段文字必须逐字不变地保留，"
            "包括标点，不得删改。可以根据文章结构调整锁定句的位置和先后顺序。"
            "相同文字若被锁定多次，必须保留相应次数。只返回修改后的完整纯正文。"
        )
        return CompletionRequest(
            model=model,
            messages=[
                self._prompts.system_message(data.settings, rule),
                self._prompts.user_payload(
                    "请进行全文修改。",
                    parent_text=data.parent_text,
                    instruction=data.instruction,
                    locked_fragments=[item.model_dump() for item in data.locked_fragments],
                ),
            ],
        )

    def selection_revision_request(
        self, model: str, data: SelectionRevisionInput
    ) -> CompletionRequest:
        selected_text = data.parent_text[data.selection.start : data.selection.end]
        prefix = data.parent_text[: data.selection.start]
        suffix = data.parent_text[data.selection.end :]
        rule = (
            "只修改 selected_text。prefix 和 suffix 必须逐字原样输出并保持原位置；"
            "locked_fragments 也必须逐字不变，选区内可按文章结构调整其位置。"
            "相同文字若被锁定多次，必须保留相应次数。只返回修改后的完整纯正文。"
        )
        return CompletionRequest(
            model=model,
            messages=[
                self._prompts.system_message(data.settings, rule),
                self._prompts.user_payload(
                    "请进行选区修改。",
                    prefix=prefix,
                    selected_text=selected_text,
                    suffix=suffix,
                    instruction=data.instruction,
                    locked_fragments=[item.model_dump() for item in data.locked_fragments],
                ),
            ],
        )
