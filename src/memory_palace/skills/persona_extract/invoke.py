"""
数字分身调用模块 (Persona Invocation)

对应 PRD 中描述的 F-014：
- 员工@分身名称并描述情况
- 系统检索逻辑档案，以第一人称风格回答
- 末尾标注「基于XX岗位2019–2024年处置记录推断」

调用流程：
    员工发送：@老王 暴雨红色预警怎么处理？
         ↓
    ask_persona(venue_id, job_title=老王, question=暴雨红色预警)
         ↓
    query_persona_logic() → 检索最相关的逻辑条目
         ↓
    第一人称格式化 + 标注来源
         ↓
    send_wechat_message()

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    llm_client = None

from ...knowledge.db_client import db_client
from ...knowledge.vector_store import get_vector_client


# =============================================================================
# 公开 API（供 wechat_bridge 等通道层调用）
# =============================================================================

async def ask_persona(
    venue_id: str,
    job_title: str,
    question: str,
    trace_id: str = "",
) -> Dict[str, Any]:
    """
    查询数字分身的经验档案并获取回答

    Args:
        venue_id: 景区ID
        job_title: 岗位名称（用于匹配分身，如"安保"、"售票"等）
        question: 员工的问题
        trace_id: 追踪ID

    Returns:
        {
            "reply_text": str,       # 第一人称回答
            "persona_id": str,       # 匹配的分身ID
            "job_title": str,        # 岗位名称
            "entries_used": int,     # 使用的逻辑条目数
            "source_note": str,      # 末尾标注
        }
    """
    logger.info(
        f"[Trace-{trace_id}] ask_persona: venue={venue_id}, "
        f"job_title={job_title}, question={question[:30]}"
    )

    # 1. 检索逻辑条目
    entries = await query_persona_logic(
        venue_id=venue_id,
        job_title=job_title,
        question=question,
        top_k=5,
        trace_id=trace_id,
    )

    if not entries:
        return {
            "reply_text": "抱歉，我目前没有这个情境的相关经验。建议您联系当班主管确认处理方式。",
            "persona_id": None,
            "job_title": job_title,
            "entries_used": 0,
            "source_note": "",
        }

    # 2. 生成第一人称回答
    reply_text = await _generate_first_person_reply(
        job_title=job_title,
        question=question,
        entries=entries,
        trace_id=trace_id,
    )

    # 3. 构建来源标注
    persona_id = entries[0].get("persona_id", "") if entries else ""
    source_note = f"基于{job_title}岗位处置记录推断"

    return {
        "reply_text": reply_text,
        "persona_id": persona_id,
        "job_title": job_title,
        "entries_used": len(entries),
        "source_note": source_note,
    }


async def query_persona_logic(
    venue_id: str,
    job_title: str,
    question: str,
    top_k: int = 5,
    threshold: float = 0.5,
    trace_id: str = "",
) -> List[Dict[str, Any]]:
    """
    检索最相关的逻辑条目

    策略：
    1. 优先从 personas 表精确匹配 job_title
    2. 如果匹配到，用向量检索entries中的相关条目
    3. 如果没有精确匹配，用问题做向量检索

    Returns:
        逻辑条目列表，每条包含 trigger/behavior/reason
    """
    # 1. 精确查找分身档案
    persona_rows = await db_client.fetch_all(
        "SELECT id, venue_id, job_title, logic_entries FROM personas WHERE job_title = ?",
        (job_title,),
    )

    if venue_id:
        # 尝试景区级别匹配
        persona_rows.extend(
            await db_client.fetch_all(
                "SELECT id, venue_id, job_title, logic_entries FROM personas WHERE job_title = ? AND venue_id = ?",
                (job_title, venue_id),
            )
        )

    if not persona_rows:
        # 2. 没有精确匹配，用向量检索兜底
        return await _vector_search_logic(question, top_k, trace_id)

    # 3. 从匹配到的档案中提取逻辑条目
    all_entries = []
    for row in persona_rows:
        try:
            entries = json.loads(row["logic_entries"])
            for entry in entries:
                entry["persona_id"] = row["id"]
                entry["job_title"] = row["job_title"]
            all_entries.extend(entries)
        except (json.JSONDecodeError, TypeError):
            continue

    if not all_entries:
        return []

    # 4. 向量检索找到最相关的条目
    return _rank_entries_by_relevance(all_entries, question, top_k, threshold)


def _rank_entries_by_relevance(
    entries: List[Dict[str, Any]],
    question: str,
    top_k: int,
    threshold: float,
) -> List[Dict[str, Any]]:
    """
    对逻辑条目按问题相关性排序（轻量级关键词匹配，无LLM开销）

    策略：
    1. 提取问句中的关键词
    2. 计算每条条目的 trigger+behavior 中关键词命中数
    3. 按命中数排序，取 top_k
    """
    # 提取问句关键词（简单分词）
    q_chars = set(question)
    scored = []

    for entry in entries:
        trigger = entry.get("trigger", "")
        behavior = entry.get("behavior", "")
        entry_text = trigger + behavior
        entry_chars = set(entry_text)

        # 计算字符重叠率
        overlap = len(q_chars & entry_chars)
        if overlap == 0:
            continue

        score = overlap / max(len(q_chars), 1)
        if score >= threshold:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


async def _vector_search_logic(
    question: str,
    top_k: int,
    trace_id: str,
) -> List[Dict[str, Any]]:
    """
    向量检索兜底（当没有精确匹配时）

    注意：当前实现用关键词模拟。正式实现应接入向量库。
    """
    # 简单关键词匹配替代向量检索
    try:
        results = get_vector_client().query_experience(
            text=question,
            top_k=top_k,
            threshold=0.5,
        )

        entries = []
        for r in results:
            content = r.get("content", "")
            # 尝试从内容中提取逻辑（简化处理）
            entries.append({
                "trigger": content[:50],
                "behavior": content[50:150] if len(content) > 50 else content,
                "reason": "",
                "persona_id": r.get("metadata", {}).get("event_id", ""),
            })
        return entries
    except Exception as e:
        logger.warning(f"[Trace-{trace_id}] 向量检索失败: {e}")
        return []


async def _generate_first_person_reply(
    job_title: str,
    question: str,
    entries: List[Dict[str, Any]],
    trace_id: str,
) -> str:
    """
    使用 LLM 将逻辑条目格式化为第一人称回答

    Prompt 要求：
    1. 用第一人称（「我会...」）
    2. 必须基于档案中的逻辑条目
    3. 末尾标注：「基于{job_title}岗位处置记录推断」
    4. 保持简洁，不超过100字
    """
    if not llm_client:
        # Mock 模式：直接拼接条目
        parts = []
        for e in entries[:2]:
            trigger = e.get("trigger", "")
            behavior = e.get("behavior", "")
            if trigger:
                parts.append(f"当{trigger}时，我会{behavior}")
        base = "；".join(parts) if parts else "根据我的经验，这种情况需要具体分析。"
        return f"{base}（基于{job_title}岗位经验推断）"

    prompt_path = Path(__file__).parent / "prompts" / "invoke.txt"
    if not prompt_path.exists():
        return f"根据我的经验，这种情况需要具体判断。"

    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 构建逻辑条目文本
    entries_text = "\n".join([
        f"- 当{entry.get('trigger', '')}时，我会{entry.get('behavior', '')}（因为{entry.get('reason', '实际经验') or '实际经验'})）"
        for entry in entries[:3]
    ])

    system_prompt = template.format(job_title=job_title)
    user_prompt = f"""档案中的相关逻辑：
{entries_text}

员工问题：{question}

请根据上述逻辑回答，保持简洁，不超过100字。"""

    try:
        llm_res = await llm_client.ask(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=200,
            json_mode=False,
            trace_id=trace_id,
        )

        reply = llm_res.content.strip()
        # 消毒回复文本
        from ...tools.llm_wrapper import INJECTION_TOKENS, _strip_control_chars
        reply = _strip_control_chars(reply)
        for token in INJECTION_TOKENS:
            if token.lower() in reply.lower():
                reply = reply.replace(token, '').replace(token.upper(), '').replace(token.lower(), '')
                logger.warning(f"[Trace-{trace_id}] reply contained injection token '{token}' — removed")
        return reply

    except Exception as e:
        logger.error(f"[Trace-{trace_id}] 分身回答生成失败: {e}")
        return "抱歉，我暂时无法回答这个问题，请联系当班主管。"
