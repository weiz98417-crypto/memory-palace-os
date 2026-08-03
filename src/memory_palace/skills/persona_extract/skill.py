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
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from ...tools.llm_wrapper import llm_client
from .. import register_skill


@register_skill("persona_extract")
class PersonaExtractSkill(BaseAgentSkill):
    """
    老员工经验萃取专家：负责将老员工的隐性经验转化为结构化逻辑条目。

    萃取流程：
        start_interview(venue_id, job_title)
             ↓
        系统返回开场白 + 第一个问题
             ↓
        员工回答 → continue_interview()
             ↓
        持续追问（4类问题循环）
             ↓
        finalize_persona() → 存入 personas 表

    逻辑条目格式：
        {
            "trigger": "当…时",
            "behavior": "我会…",
            "reason": "因为…"
        }
    """

    TOTAL_QUESTIONS = 4
    SUMMARY_STATE = 6

    def __init__(self, db_client=None):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()
        self.db_client = db_client
        self._interview_state: Dict[str, Any] = {}

        super().__init__(
            skill_name=self.config.get("agent_metadata", {}).get("name", "PersonaExtract_Skill"),
            model_name=self.config.get("llm_config", {}).get("model", "deepseek-v4-flash"),
        )

    def _load_config(self) -> Dict[str, Any]:
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            return {
                "agent_metadata": {"name": "PersonaExtract_Skill"},
                "llm_config": {"model": "deepseek-v4-flash", "temperature": 0.3},
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

    def interview_prompt(self, current_question: int) -> Dict[str, Any]:
        if current_question == self.SUMMARY_STATE:
            return {
                "reply_text": self._load_prompt("extract_summary.txt"),
                "current_question": self.TOTAL_QUESTIONS,
                "total_questions": self.TOTAL_QUESTIONS,
                "stage": "summary",
                "prompt_finalize": True,
            }
        if 1 <= current_question <= self.TOTAL_QUESTIONS:
            return {
                "reply_text": self._load_prompt(f"extract_question_{current_question}.txt"),
                "current_question": current_question,
                "total_questions": self.TOTAL_QUESTIONS,
                "stage": f"question_{current_question}",
                "prompt_finalize": False,
            }
        raise ValueError(f"无效的访谈问题状态: {current_question}")

    async def _create_interview_state(
        self,
        interview_id: str,
        state: Dict[str, Any],
        trace_id: str,
    ) -> None:
        if self.db_client is None:
            self._interview_state[interview_id] = dict(state)
            return
        now = time.time()
        await self.db_client.execute(
            """
            INSERT INTO persona_interviews (
                id, venue_id, source_persona_id, job_title, current_question,
                all_entries_json, raw_answers_json, status, created_by,
                trace_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
            """,
            (
                interview_id,
                state["venue_id"],
                state.get("source_persona_id"),
                state["job_title"],
                state["current_question"],
                json.dumps(state["all_entries"], ensure_ascii=False),
                json.dumps(state["raw_answers"], ensure_ascii=False),
                state.get("created_by"),
                trace_id,
                now,
                now,
            ),
        )

    async def _load_interview_state(
        self,
        interview_id: str,
        venue_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if self.db_client is None:
            state = self._interview_state.get(interview_id)
            if state is None or (venue_id and state.get("venue_id") != venue_id):
                return None
            return state
        sql = "SELECT * FROM persona_interviews WHERE id = ? AND status = 'ACTIVE'"
        params: list[Any] = [interview_id]
        if venue_id:
            sql += " AND venue_id = ?"
            params.append(venue_id)
        row = await self.db_client.fetch_one(sql, tuple(params))
        if row is None:
            return None
        raw_answers = json.loads(row.get("raw_answers_json") or "{}")
        return {
            "venue_id": row["venue_id"],
            "job_title": row["job_title"],
            "current_question": int(row["current_question"]),
            "all_entries": json.loads(row.get("all_entries_json") or "[]"),
            "raw_answers": {int(key): value for key, value in raw_answers.items()},
            "completed": False,
            "source_persona_id": row.get("source_persona_id"),
            "created_by": row.get("created_by"),
        }

    async def _persist_interview_state(
        self,
        interview_id: str,
        state: Dict[str, Any],
    ) -> None:
        if self.db_client is None:
            self._interview_state[interview_id] = state
            return
        rowcount = await self.db_client.execute(
            """
            UPDATE persona_interviews
            SET current_question = ?, all_entries_json = ?, raw_answers_json = ?, updated_at = ?
            WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'
            """,
            (
                state["current_question"],
                json.dumps(state["all_entries"], ensure_ascii=False),
                json.dumps(state["raw_answers"], ensure_ascii=False),
                time.time(),
                interview_id,
                state["venue_id"],
            ),
        )
        if rowcount == 0:
            raise RuntimeError("访谈状态已变化，无法保存当前回答")

    async def _complete_interview_state(
        self,
        interview_id: str,
        state: Dict[str, Any],
    ) -> None:
        if self.db_client is None:
            self._interview_state.pop(interview_id, None)
            return
        now = time.time()
        rowcount = await self.db_client.execute(
            """
            UPDATE persona_interviews
            SET current_question = ?, all_entries_json = ?, raw_answers_json = ?,
                status = 'COMPLETED', updated_at = ?, completed_at = ?
            WHERE id = ? AND venue_id = ? AND status = 'ACTIVE'
            """,
            (
                state["current_question"],
                json.dumps(state["all_entries"], ensure_ascii=False),
                json.dumps(state["raw_answers"], ensure_ascii=False),
                now,
                now,
                interview_id,
                state["venue_id"],
            ),
        )
        if rowcount == 0:
            raise RuntimeError("访谈状态已变化，无法完成归档")

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
                created_by=context.get("created_by"),
            )
        elif action == "continue":
            return await self._continue_interview(
                interview_id=context["interview_id"],
                answer=context["answer"],
                trace_id=trace_id,
                venue_id=context.get("venue_id"),
            )
        elif action == "finalize":
            return await self._finalize_persona(
                interview_id=context["interview_id"],
                trace_id=trace_id,
                venue_id=context.get("venue_id"),
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
        created_by: Optional[str] = None,
    ) -> SkillOutput:
        """开始访谈：返回开场白 + 第一个问题"""
        interview_id = str(uuid.uuid4())[:12]

        state = {
            "venue_id": venue_id,
            "job_title": job_title,
            "current_question": 1,
            "all_entries": [],
            "raw_answers": {},
            "completed": False,
            "source_persona_id": source_persona_id,
            "created_by": created_by,
        }
        await self._create_interview_state(interview_id, state, trace_id)

        logger.info(
            f"[Trace-{trace_id}] PersonaExtract 开启访谈: "
            f"id={interview_id}, job_title={job_title}"
        )

        intro_text = self._load_prompt("extract_intro.txt").replace("【岗位名称】", job_title)
        question = self.interview_prompt(1)

        reply_text = f"{intro_text}\n\n---\n\n{question['reply_text']}"

        return SkillOutput(
            success=True,
            reply_text=reply_text,
            structured_data={
                "interview_id": interview_id,
                "action": "start",
                "current_question": 1,
                "question_count": self.TOTAL_QUESTIONS,
                "total_questions": self.TOTAL_QUESTIONS,
                "stage": "question_1",
            },
            action_taken="persona_extract_start",
        )

    async def _continue_interview(
        self,
        interview_id: str,
        answer: str,
        trace_id: str,
        venue_id: Optional[str] = None,
    ) -> SkillOutput:
        """继续访谈：解析回答，决定是追问还是进入下一题"""
        state = await self._load_interview_state(interview_id, venue_id)
        if state is None:
            return SkillOutput(
                success=False,
                reply_text="未找到对应的访谈，请先调用 start_interview",
                structured_data={"error": "interview_not_found"},
                action_taken="interview_not_found",
            )

        current_q = state["current_question"]
        job_title = state["job_title"]

        # 解析员工回答，提取逻辑条目
        entries = await self._parse_answer(
            question_id=current_q,
            answer=answer,
            job_title=job_title,
            trace_id=trace_id,
            venue_id=state["venue_id"],
        )

        state["all_entries"].extend(entries)
        state["raw_answers"][current_q] = answer

        # 决定下一题（当前有4个问题文件，Q4后进入总结）
        if current_q < self.TOTAL_QUESTIONS:
            next_q = current_q + 1
            state["current_question"] = next_q
            await self._persist_interview_state(interview_id, state)
            question = self.interview_prompt(next_q)

            return SkillOutput(
                success=True,
                reply_text=question["reply_text"],
                structured_data={
                    "interview_id": interview_id,
                    "action": "continue",
                    "current_question": next_q,
                    "total_questions": self.TOTAL_QUESTIONS,
                    "extracted_entries_count": len(entries),
                    "total_entries": len(state["all_entries"]),
                    "stage": question["stage"],
                },
                action_taken="persona_extract_continue",
            )
        else:
            # 最后一题，进入总结
            summary = self.interview_prompt(self.SUMMARY_STATE)
            state["current_question"] = self.SUMMARY_STATE
            await self._persist_interview_state(interview_id, state)

            return SkillOutput(
                success=True,
                reply_text=summary["reply_text"],
                structured_data={
                    "interview_id": interview_id,
                    "action": "continue",
                    "current_question": self.TOTAL_QUESTIONS,
                    "total_questions": self.TOTAL_QUESTIONS,
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
        venue_id: Optional[str] = None,
    ) -> SkillOutput:
        """完成访谈：汇总所有条目，存入 personas 表"""
        state = await self._load_interview_state(interview_id, venue_id)
        if state is None:
            return SkillOutput(
                success=False,
                reply_text="未找到对应的访谈",
                structured_data={"error": "interview_not_found"},
                action_taken="interview_not_found",
            )

        if state["current_question"] != self.SUMMARY_STATE:
            return SkillOutput(
                success=False,
                reply_text="访谈尚未完成全部问题，不能提前结束",
                structured_data={"error": "interview_not_ready"},
                action_taken="interview_not_ready",
            )

        # 最终解析（处理总结问题的回答）
        if self.SUMMARY_STATE in state["raw_answers"]:
            final_entries = await self._parse_answer(
                question_id=5,
                answer=state["raw_answers"][self.SUMMARY_STATE],
                job_title=state["job_title"],
                trace_id=trace_id,
                venue_id=state["venue_id"],
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

        await self._complete_interview_state(interview_id, state)

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
        venue_id: str,
    ) -> List[Dict[str, str]]:
        """调用 LLM 解析员工回答，提取逻辑条目"""
        prompt_template = self._load_prompt(f"extract_question_{question_id}.txt")

        system_prompt = prompt_template.strip()
        user_prompt = f"员工回答：\n{answer}\n\n请提取逻辑条目，返回 JSON 格式"

        if not llm_client:
            raise RuntimeError("PersonaExtract LLM 客户端未初始化，不能提取知识条目")

        try:
            llm_res = await llm_client.ask(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model_name,
                temperature=0.3,
                max_tokens=1000,
                json_mode=True,
                trace_id=trace_id,
                venue_id=venue_id,
                agent_id="PersonaExtract",
                agent_name=self.skill_name,
            )

            if getattr(llm_res, "is_mock", False):
                return self._mock_parse(answer, question_id)

            parsed = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

            # 统一提取逻辑条目
            entries = []
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "trigger" in item and "behavior" in item:
                        entries.append({
                            "trigger": item.get("trigger", ""),
                            "behavior": item.get("behavior", ""),
                            "reason": item.get("reason", ""),
                        })

            if isinstance(parsed, dict):
                for key in ["logic_entries", "summary_logic_entries", "error_cases", "counter_intuitive_cases"]:
                    if not isinstance(parsed.get(key), list):
                        continue
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

            if not entries:
                raise ValueError("LLM 返回结果不包含可用的知识条目")

            return entries

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] 解析回答异常: {e}")
            raise

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
        """显式 MOCK_LLM 测试模式下生成可识别的占位条目。"""
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
        if self.db_client is None:
            from ...knowledge.db_client import db_client
        else:
            db_client = self.db_client
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
                rowcount = await db_client.execute(
                    """UPDATE personas SET logic_entries = ?, raw_answers = ?, updated_at = ? WHERE id = ? AND venue_id = ?""",
                    (
                        json.dumps(sanitized_entries, ensure_ascii=False),
                        json.dumps(raw_answers, ensure_ascii=False),
                        now,
                        persona_id,
                        venue_id,
                    ),
                )
                if rowcount == 0:
                    raise RuntimeError("目标 Persona 不存在或不属于当前场地")
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
        state = await self._load_interview_state(interview_id)
        state = state or {}
        entries = state.get("all_entries", [])
        result = await self._finalize_persona(
            interview_id=interview_id, trace_id=trace_id
        )
        # Inject entries into structured_data for API response
        if result.structured_data:
            result.structured_data["entries"] = entries
        return result
