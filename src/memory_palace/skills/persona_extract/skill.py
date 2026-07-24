"""
老员工经验萃取专家智能体 (Persona Extract Skill Implementation)

对应 PRD 中描述的结构化访谈萃取系统（F-013）：
- 每次约1小时结构化访谈
- 5类核心问题框架
- 提取「判断逻辑」而非「知识内容」
- 逻辑条目格式：{trigger, behavior, reason}

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，PersonaExtract 将以模拟模式运行")
    llm_client = None


@register_skill("persona_extract")
class PersonaExtractSkill(BaseAgentSkill):
    # 类级别状态（所有实例共享 interview_state）
    _interview_state: Dict[str, Any] = {}

    """
    老员工经验萃取专家：负责将老员工的隐性经验转化为结构化逻辑条目。

    萃取流程：
        start_interview(venue_id, job_title)
             ↓
        系统返回开场白 + 第一个问题
             ↓
        员工回答 → continue_interview()
             ↓
        持续追问（5类问题循环）
             ↓
        finalize_persona() → 存入 personas 表

    逻辑条目格式：
        {
            "trigger": "当…时",
            "behavior": "我会…",
            "reason": "因为…"
        }
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_metadata", {}).get("name", "PersonaExtract_Skill"),
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4o"),
        )

    def _load_config(self) -> Dict[str, Any]:
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            return {
                "agent_metadata": {"name": "PersonaExtract_Skill"},
                "llm_config": {"model": "gpt-4o", "temperature": 0.3},
                "max_questions": 8,
            }
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_prompt(self, filename: str) -> str:
        """加载 Prompt 文件"""
        prompt_path = self.base_path / "prompts" / filename
        if not prompt_path.exists():
            raise FileNotFoundError(f"未找到 Prompt: {prompt_path}")
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """入参校验"""
        action = context.get("action", "")

        if action == "start":
            if "job_title" not in context:
                raise SkillValidationError("start_interview 需要 'job_title' 字段")
        elif action == "continue":
            if "interview_id" not in context:
                raise SkillValidationError("continue_interview 需要 'interview_id' 字段")
            if "answer" not in context:
                raise SkillValidationError("continue_interview 需要 'answer' 字段")
        elif action == "finalize":
            if "interview_id" not in context:
                raise SkillValidationError("finalize_persona 需要 'interview_id' 字段")

    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """分发到具体的访谈阶段方法"""
        action = context.get("action", "")

        if action == "start":
            return await self._start_interview(
                venue_id=context.get("venue_id", ""),
                job_title=context["job_title"],
                trace_id=trace_id,
                source_persona_id=context.get("source_persona_id"),
            )
        elif action == "continue":
            return await self._continue_interview(
                interview_id=context["interview_id"],
                answer=context["answer"],
                trace_id=trace_id,
            )
        elif action == "finalize":
            return await self._finalize_persona(
                interview_id=context["interview_id"],
                trace_id=trace_id,
            )
        else:
            return SkillOutput(
                success=False,
                reply_text="未知 action，请使用 start / continue / finalize",
                structured_data={"error": f"unknown_action: {action}"},
                action_taken="unknown_action",
            )

    # =========================================================================
    # 访谈阶段方法
    # =========================================================================

    async def _start_interview(
        self,
        venue_id: str,
        job_title: str,
        trace_id: str,
        source_persona_id: Optional[str] = None,
    ) -> SkillOutput:
        """开始访谈：返回开场白 + 第一个问题"""
        interview_id = str(uuid.uuid4())[:12]

        self._interview_state[interview_id] = {
            "venue_id": venue_id,
            "job_title": job_title,
            "current_question": 1,
            "all_entries": [],
            "raw_answers": {},
            "completed": False,
            "source_persona_id": source_persona_id,  # 用于 finalize 时更新原分身
        }

        logger.info(
            f"[Trace-{trace_id}] PersonaExtract 开启访谈: "
            f"id={interview_id}, job_title={job_title}"
        )

        intro_text = self._load_prompt("extract_intro.txt").replace("【岗位名称】", job_title)
        question_1_text = self._load_prompt("extract_question_1.txt")

        reply_text = f"{intro_text}\n\n---\n\n{question_1_text}"

        return SkillOutput(
            success=True,
            reply_text=reply_text,
            structured_data={
                "interview_id": interview_id,
                "action": "start",
                "current_question": 1,
                "question_count": 5,
                "total_questions": 5,
                "stage": "question_1",
            },
            action_taken="persona_extract_start",
        )

    async def _continue_interview(
        self,
        interview_id: str,
        answer: str,
        trace_id: str,
    ) -> SkillOutput:
        """继续访谈：解析回答，决定是追问还是进入下一题"""
        if interview_id not in self._interview_state:
            return SkillOutput(
                success=False,
                reply_text="未找到对应的访谈，请先调用 start_interview",
                structured_data={"error": "interview_not_found"},
                action_taken="interview_not_found",
            )

        state = self._interview_state[interview_id]
        current_q = state["current_question"]
        job_title = state["job_title"]

        # 解析员工回答，提取逻辑条目
        entries = await self._parse_answer(
            question_id=current_q,
            answer=answer,
            job_title=job_title,
            trace_id=trace_id,
        )

        state["all_entries"].extend(entries)
        state["raw_answers"][current_q] = answer

        # 决定下一题（当前有4个问题文件，Q4后进入总结）
        if current_q < 4:
            next_q = current_q + 1
            state["current_question"] = next_q
            question_text = self._load_prompt(f"extract_question_{next_q}.txt")
            reply_text = f"{question_text}"

            stage = f"question_{next_q}"
            return SkillOutput(
                success=True,
                reply_text=reply_text,
                structured_data={
                    "interview_id": interview_id,
                    "action": "continue",
                    "current_question": next_q,
                    "extracted_entries_count": len(entries),
                    "total_entries": len(state["all_entries"]),
                    "stage": stage,
                },
                action_taken="persona_extract_continue",
            )
        else:
            # 最后一题，进入总结
            summary_text = self._load_prompt("extract_summary.txt")
            state["current_question"] = 6  # 标记已到总结阶段

            reply_text = f"{summary_text}"

            return SkillOutput(
                success=True,
                reply_text=reply_text,
                structured_data={
                    "interview_id": interview_id,
                    "action": "continue",
                    "current_question": 6,
                    "extracted_entries_count": len(entries),
                    "total_entries": len(state["all_entries"]),
                    "stage": "summary",
                    "prompt_finalize": True,
                },
                action_taken="persona_extract_summary_ready",
            )

    async def _finalize_persona(
        self,
        interview_id: str,
        trace_id: str,
    ) -> SkillOutput:
        """完成访谈：汇总所有条目，存入 personas 表"""
        if interview_id not in self._interview_state:
            return SkillOutput(
                success=False,
                reply_text="未找到对应的访谈",
                structured_data={"error": "interview_not_found"},
                action_taken="interview_not_found",
            )

        state = self._interview_state[interview_id]

        # 最终解析（处理总结问题的回答）
        if 6 in state["raw_answers"]:
            final_entries = await self._parse_answer(
                question_id=5,
                answer=state["raw_answers"][6],
                job_title=state["job_title"],
                trace_id=trace_id,
            )
            state["all_entries"].extend(final_entries)

        # 生成感谢话术
        thanks_text = self._load_prompt("extract_summary.txt")
        thanks_text = thanks_text.split("### 萃取完成话术")[1].split("### 输出格式")[0].strip()

        # 存入数据库
        persona_id = await self._save_persona(
            venue_id=state["venue_id"],
            job_title=state["job_title"],
            logic_entries=state["all_entries"],
            raw_answers=state["raw_answers"],
            trace_id=trace_id,
            target_persona_id=state.get("source_persona_id"),
        )

        # 清理内存状态
        del self._interview_state[interview_id]

        logger.info(
            f"[Trace-{trace_id}] PersonaExtract 完成萃取: "
            f"persona_id={persona_id}, entries={len(state['all_entries'])}"
        )

        return SkillOutput(
            success=True,
            reply_text=thanks_text,
            structured_data={
                "persona_id": persona_id,
                "job_title": state["job_title"],
                "total_entries": len(state["all_entries"]),
                "action": "finalize_completed",
            },
            action_taken="persona_extract_finalized",
        )

    # =========================================================================
    # LLM 解析与存储
    # =========================================================================

    async def _parse_answer(
        self,
        question_id: int,
        answer: str,
        job_title: str,
        trace_id: str,
    ) -> List[Dict[str, str]]:
        """调用 LLM 解析员工回答，提取逻辑条目"""
        prompt_path = self.base_path / "prompts" / f"extract_question_{question_id}.txt"
        prompt_template = self._load_prompt(f"extract_question_{question_id}.txt")

        system_prompt = prompt_template.split("### 输出格式")[0].strip()
        user_prompt = f"员工回答：\n{answer}\n\n请提取逻辑条目，返回 JSON 格式"

        if not llm_client:
            return self._mock_parse(answer, question_id)

        try:
            llm_res = await llm_client.ask(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model_name,
                temperature=0.3,
                max_tokens=1000,
                json_mode=True,
                trace_id=trace_id,
            )

            parsed = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

            # 统一提取逻辑条目
            entries = []
            for key in ["logic_entries", "summary_logic_entries", "error_cases", "counter_intuitive_cases"]:
                if key in parsed and isinstance(parsed[key], list):
                    for item in parsed[key]:
                        if isinstance(item, dict):
                            if key in ["error_cases", "counter_intuitive_cases"]:
                                entries.append(self._normalize_entry(item, key))
                            elif "trigger" in item and "behavior" in item:
                                entries.append({
                                    "trigger": item.get("trigger", ""),
                                    "behavior": item.get("behavior", ""),
                                    "reason": item.get("reason", ""),
                                })

            # Also try top-level "entries" key (DeepSeek may use this)
            if not entries and isinstance(parsed, dict):
                top = parsed.get("entries", [])
                if isinstance(top, list):
                    for item in top:
                        if isinstance(item, dict) and "trigger" in item and "behavior" in item:
                            entries.append({
                                "trigger": item.get("trigger", ""),
                                "behavior": item.get("behavior", ""),
                                "reason": item.get("reason", ""),
                            })

            # Fallback: LLM returned nothing usable, generate mock entries for demo
            if not entries:
                logger.warning(f"[Trace-{trace_id}] LLM no entries found, using mock fallback")
                entries = self._mock_parse(answer, question_id)

            return entries

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] 解析回答异常: {e}")
            return self._mock_parse(answer, question_id)

    def _normalize_entry(self, item: Dict[str, Any], entry_type: str) -> Dict[str, str]:
        """将不同格式的条目统一转换为 {trigger, behavior, reason}"""
        if entry_type == "error_cases":
            return {
                "trigger": item.get("situation", ""),
                "behavior": item.get("correct_judgment", ""),
                "reason": item.get("lesson", ""),
            }
        elif entry_type == "counter_intuitive_cases":
            return {
                "trigger": item.get("intuitive_action", ""),
                "behavior": item.get("actual_action", ""),
                "reason": item.get("outcome", ""),
            }
        return {"trigger": "", "behavior": "", "reason": ""}

    def _mock_parse(self, answer: str, question_id: int) -> List[Dict[str, str]]:
        """Mock 模式：无法调用 LLM 时的兜底"""
        return [
            {
                "trigger": f"[Q{question_id}] 从回答中提取的触发条件",
                "behavior": f"[Q{question_id}] 从回答中提取的判断行为",
                "reason": "[Mock] LLM 不可用，仅作占位符",
            }
        ]

    async def _save_persona(
        self,
        venue_id: str,
        job_title: str,
        logic_entries: List[Dict[str, str]],
        raw_answers: Dict[int, str],
        trace_id: str,
        target_persona_id: Optional[str] = None,
    ) -> str:
        """将萃取结果存入 personas 表；若指定了 target_persona_id 则更新现有记录"""
        from ...knowledge.db_client import db_client
        from ...tools.llm_wrapper import sanitize_llm_output
        import time as _time

        now = _time.time()

        # 消毒每条 logic_entry
        sanitized_entries = []
        for entry in logic_entries:
            cleaned, warns = sanitize_llm_output(entry, "logic_entry", trace_id=trace_id)
            if cleaned:
                sanitized_entries.append(cleaned)
        if len(sanitized_entries) < len(logic_entries):
            logger.warning(f"[Trace-{trace_id}] {len(logic_entries) - len(sanitized_entries)} entry(s) rejected by sanitizer")

        try:
            if target_persona_id:
                # 更新已有分身
                persona_id = target_persona_id
                await db_client.execute(
                    """UPDATE personas SET logic_entries = ?, raw_answers = ?, updated_at = ? WHERE id = ?""",
                    (
                        json.dumps(sanitized_entries, ensure_ascii=False),
                        json.dumps(raw_answers, ensure_ascii=False),
                        now,
                        persona_id,
                    ),
                )
                logger.info(f"[Trace-{trace_id}] Persona 档案已更新: id={persona_id}")
            else:
                # 新建分身
                persona_id = str(uuid.uuid4())
                await db_client.execute(
                    """
                    INSERT INTO personas (id, venue_id, job_title, logic_entries, raw_answers, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persona_id,
                        venue_id,
                        job_title,
                        json.dumps(sanitized_entries, ensure_ascii=False),
                        json.dumps(raw_answers, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                logger.info(f"[Trace-{trace_id}] Persona 档案已保存: id={persona_id}")

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Persona 档案保存失败: {e}")
            raise

        return persona_id

    # =========================================================================
    # Demo API public wrappers (for /demo/persona/interview/* endpoints)
    # =========================================================================

    async def start_interview(
        self, job_title: str, venue_id: str = "", trace_id: str = "demo"
    ) -> SkillOutput:
        """Public wrapper: start interview with corrected param order and question count."""
        result = await self._start_interview(
            venue_id=venue_id, job_title=job_title, trace_id=trace_id
        )
        # Fix hardcoded total_questions: internal says 5, actual flow has 4
        if result.structured_data:
            result.structured_data["total_questions"] = 4
        return result

    async def continue_interview(
        self, interview_id: str, answer: str, trace_id: str = "demo"
    ) -> SkillOutput:
        """Public wrapper: continue interview with a user answer."""
        return await self._continue_interview(
            interview_id=interview_id, answer=answer, trace_id=trace_id
        )

    async def finalize_interview(
        self, interview_id: str, trace_id: str = "demo"
    ) -> SkillOutput:
        """Public wrapper: finalize interview, save persona to DB, return entries."""
        # Snapshot entries before _finalize_persona clears interview state
        state = self._interview_state.get(interview_id, {})
        entries = state.get("all_entries", [])
        result = await self._finalize_persona(
            interview_id=interview_id, trace_id=trace_id
        )
        # Inject entries into structured_data for API response
        if result.structured_data:
            result.structured_data["entries"] = entries
        return result
