"""Governed lifecycle, authorization, and extraction rules for experience assets."""

from collections.abc import Iterable, Mapping
import json
from typing import Any


class ExperienceStateError(ValueError):
    """Raised when an experience card lifecycle transition is not allowed."""


class ExperienceDraftExtractionError(RuntimeError):
    """Raised when interview evidence cannot produce a governed experience draft."""


EXPERIENCE_DRAFT_FIELDS = (
    "title",
    "applicable_context",
    "signals",
    "decision_rule",
    "recommended_actions",
    "rationale",
    "prohibitions",
    "exceptions",
    "source_excerpts",
)


def _evidence_source_excerpts(evidence: Mapping[str, Any]) -> list[str]:
    excerpts: list[str] = []
    for turn in evidence.get("turns") or []:
        if not isinstance(turn, Mapping):
            continue
        answer = str(turn.get("answer_text") or "").strip()
        if not answer:
            continue
        submitted = str(turn.get("source_excerpt") or "").strip()
        excerpt = submitted if submitted and submitted in answer else answer
        excerpts.append(excerpt[:2000])
    return excerpts


class DeepSeekExperienceDraftExtractor:
    """Turn persisted interview evidence into one validated experience-card draft."""

    model_name = "deepseek-flash"
    agent_name = "PersonaExtract"

    def __init__(self, llm_client: Any):
        if llm_client is None:
            raise ExperienceDraftExtractionError("PersonaExtract LLM 客户端未初始化")
        self._llm = llm_client

    async def extract(
        self,
        evidence: Mapping[str, Any],
        *,
        trace_id: str,
        venue_id: str,
    ) -> dict[str, Any]:
        turns = list(evidence.get("turns") or [])
        if not turns:
            raise ExperienceDraftExtractionError("访谈没有可供萃取的回答")

        transcript = "\n\n".join(
            f"第{turn.get('turn_number')}轮\n问题：{turn.get('question_text', '')}\n"
            f"回答：{turn.get('answer_text', '')}"
            for turn in turns
        )
        system_prompt = """你是企业经验萃取 Agent PersonaExtract。只能依据访谈原文生成经验卡，不能补造事实。
返回一个 JSON 对象，且只能包含以下字段：
- title: 简洁业务标题
- applicable_context: 适用情境
- signals: 判断信号字符串数组
- decision_rule: 判断规则
- recommended_actions: 建议动作字符串数组
- rationale: 判断依据
- prohibitions: 禁止事项字符串数组
- exceptions: 例外和升级条件字符串数组
- source_excerpts: 从员工回答逐字复制的原文片段字符串数组
每个字段都必须非空。SOP 或制度要求不得被个人经验覆盖。不要返回 Markdown、代码围栏或内部字段名。"""
        user_prompt = (
            f"访谈主题：{evidence.get('title', '')}\n"
            f"来源专家：{evidence.get('expert_name', '')} · {evidence.get('expert_job_title', '')}\n"
            f"来源事件：{evidence.get('source_event_id') or '暂无'}\n\n"
            f"访谈原文：\n{transcript}"
        )
        try:
            response = await self._llm.ask(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model_name,
                temperature=0.2,
                max_tokens=1800,
                json_mode=True,
                trace_id=trace_id,
                venue_id=venue_id,
                agent_id=self.agent_name,
                agent_name=self.agent_name,
            )
            if getattr(response, "is_mock", False):
                raise ExperienceDraftExtractionError("正式经验萃取不接受 Mock 模型结果")
            parsed = await self._llm.parse_json(response.content, trace_id=trace_id)
        except ExperienceDraftExtractionError:
            raise
        except Exception as exc:
            raise ExperienceDraftExtractionError("DeepSeek 经验萃取失败") from exc

        if isinstance(parsed, Mapping):
            parsed = dict(parsed)
            source_excerpts = _evidence_source_excerpts(evidence)
            if source_excerpts:
                parsed["source_excerpts"] = source_excerpts
        return validate_extracted_experience_draft(parsed, evidence)


def validate_extracted_experience_draft(
    draft: Any,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the adapter result and preserve only the public experience contract."""
    if not isinstance(draft, Mapping):
        raise ExperienceDraftExtractionError("经验萃取结果不是结构化对象")

    text_fields = ("title", "applicable_context", "decision_rule", "rationale")
    list_fields = (
        "signals",
        "recommended_actions",
        "prohibitions",
        "exceptions",
        "source_excerpts",
    )
    normalized: dict[str, Any] = {}
    for field in text_fields:
        value = draft.get(field)
        if not isinstance(value, str) or len(value.strip()) < 2:
            raise ExperienceDraftExtractionError(f"经验萃取结果缺少字段：{field}")
        normalized[field] = value.strip()[:4000]

    for field in list_fields:
        value = draft.get(field)
        if not isinstance(value, list):
            raise ExperienceDraftExtractionError(f"经验萃取结果缺少字段：{field}")
        items = [str(item).strip()[:2000] for item in value if isinstance(item, str) and item.strip()]
        if not items:
            raise ExperienceDraftExtractionError(f"经验萃取结果缺少字段：{field}")
        normalized[field] = items[:100]

    answer_text = "\n".join(
        str(turn.get("answer_text") or "") for turn in evidence.get("turns") or []
    )
    if not all(excerpt in answer_text for excerpt in normalized["source_excerpts"]):
        raise ExperienceDraftExtractionError("经验来源片段无法回溯到访谈原文")

    # A JSON round-trip rejects custom mapping/list implementations before persistence.
    return json.loads(json.dumps(normalized, ensure_ascii=False))


_EXPERIENCE_TRANSITIONS = {
    ("DRAFT", "confirm"): "EXPERT_CONFIRMED",
    ("EXPERT_CONFIRMED", "submit"): "IN_REVIEW",
    ("IN_REVIEW", "reject"): "DRAFT",
    ("IN_REVIEW", "publish"): "PUBLISHED",
    ("PUBLISHED", "deprecate"): "DEPRECATED",
}

_PRINCIPAL_SCOPE_FIELDS = {
    "USER": "user_id",
    "ROLE": "role",
    "DEPARTMENT": "department",
    "JOB_TITLE": "job_title",
}


def next_experience_status(current: str, action: str) -> str:
    """Return the governed next status or reject the requested transition."""
    try:
        return _EXPERIENCE_TRANSITIONS[(current, action)]
    except (KeyError, TypeError) as exc:
        raise ExperienceStateError(
            f"Experience transition is not allowed: {current!r} + {action!r}"
        ) from exc


def authorization_allows(
    venue_id: str,
    scopes: Iterable[Mapping[str, Any]] | None,
    principal: Mapping[str, Any] | None,
) -> bool:
    """Return whether a same-venue principal matches an explicit asset scope."""
    if not venue_id or not principal or not scopes:
        return False

    principal_venue = principal.get("venue_id") or principal.get("tenant_id")
    if principal_venue != venue_id:
        return False

    for scope in scopes:
        if not isinstance(scope, Mapping):
            continue

        scope_type = scope.get("scope_type")
        scope_value = scope.get("scope_value")
        if not isinstance(scope_type, str) or scope_value is None:
            continue

        normalized_type = scope_type.upper()
        if normalized_type == "VENUE":
            candidate = venue_id
        else:
            principal_field = _PRINCIPAL_SCOPE_FIELDS.get(normalized_type)
            if principal_field is None:
                continue
            candidate = principal.get(principal_field)

        if candidate is not None and str(candidate) == str(scope_value):
            return True

    return False
