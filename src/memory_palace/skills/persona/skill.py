"""Evidence-constrained Persona expression for the unified assistant."""

import yaml
import json
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from ...tools.llm_wrapper import llm_client
from .. import register_skill


@register_skill("persona")
class PersonaSkill(BaseAgentSkill):
    """Express authorized experience without impersonating the source expert."""

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_name", "Persona_Expert_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "deepseek-flash")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载分身专属的运行时配置"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("Persona config 缺失，采用默认对话参数。")
            return {
                "agent_name": "Persona_Expert_Agent",
                "llm_config": {"model": "deepseek-flash", "temperature": 0.5},
                "memory_config": {"max_history_turns": 5}
            }

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_prompt_template(self) -> str:
        """加载分身人设 Prompt (对应项目树中的 interview.txt)"""
        prompt_path = self.base_path / "prompts" / "interview.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"致命错误：未找到分身人设模板 {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """Validate unified-assistant input and any governed evidence."""
        if "raw_text" not in context or not str(context["raw_text"]).strip():
            raise SkillValidationError("Persona 缺少用户输入的 'raw_text'。")
        experience_references = self._experience_references(context)
        if not experience_references:
            raise SkillValidationError("Persona 只能使用已发布且已授权的专家经验。")
        if context.get("persona_trigger") not in {
            "AUTHORIZED_RETRIEVAL",
            "EXPLICIT_EXPERT",
        }:
            raise SkillValidationError("Persona 缺少可审计的专家经验授权触发来源。")

    @staticmethod
    def _experience_references(context: Dict[str, Any]) -> List[Dict[str, Any]]:
        references = context.get("knowledge_references") or []
        if not isinstance(references, list):
            raise SkillValidationError("Persona 的知识引用必须是列表。")

        experience_references = []
        required = {
            "source_id",
            "source_type",
            "source_label",
            "title",
            "version",
            "status",
            "expert_name",
            "content",
        }
        for reference in references:
            if not isinstance(reference, dict):
                continue
            source_type = str(reference.get("source_type") or "").upper()
            if source_type not in {"EXPERIENCE", "EXPERIENCE_CARD"}:
                continue
            if not required.issubset(reference):
                raise SkillValidationError("Persona 收到的专家经验缺少来源字段。")
            if str(reference.get("status") or "").upper() != "PUBLISHED":
                raise SkillValidationError("Persona 只能使用已发布的专家经验。")
            if any(reference.get(field) in {None, ""} for field in required):
                raise SkillValidationError("Persona 收到的专家经验存在空来源字段。")
            experience_references.append(dict(reference))
        return experience_references

    def _format_history_window(self, history: List[Dict[str, str]]) -> str:
        """
        工业级滑动窗口机制 (Sliding Window Context):
        将最近的 N 轮对话历史格式化为字符串，注入到 Prompt 中，赋予大模型"记忆"。
        """
        if not history:
            return "【当前为首次对话，无历史记录】"

        max_turns = self.config.get("memory_config", {}).get("max_history_turns", 5)
        recent_history = history[-(max_turns * 2):]

        formatted_str = ""
        for msg in recent_history:
            role_name = "员工" if msg.get("role") == "user" else "企业运营助手"
            content = msg.get("content", "").replace("\n", " ")
            formatted_str += f"[{role_name}]: {content}\n"

        return formatted_str.strip()

    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """Generate a governed assistant response from explicit evidence."""
        query_text = str(context["raw_text"]).strip()
        chat_history = context.get("history", [])
        knowledge_references = context.get("knowledge_references") or []
        experience_references = self._experience_references(context)
        response_mode = "AUTHORIZED_EXPERIENCE_SYNTHESIS"

        logger.info(
            f"[Trace-{trace_id}] Persona 启动统一助手表达 | "
            f"模式={response_mode} | 历史轮数={len(chat_history)}"
        )

        try:
            formatted_history = self._format_history_window(chat_history)
            template = self._load_prompt_template()
            evidence_context = json.dumps(
                knowledge_references,
                ensure_ascii=False,
                default=str,
            )
            full_system_prompt = template.format(
                chat_history=formatted_history,
                response_mode=response_mode,
                evidence_context=evidence_context,
            )

            if not llm_client:
                raise RuntimeError("Persona LLM 客户端未初始化，不能生成分身回答")

            llm_params = self.config.get("llm_config", {})

            llm_res = await llm_client.ask(
                system_prompt=full_system_prompt,
                user_prompt=f"员工最新回复：{query_text}",
                model=self.model_name,
                temperature=llm_params.get("temperature", 0.5),
                json_mode=True,
                trace_id=trace_id,
                venue_id=context.get("venue_id", ""),
                agent_id="Persona",
                agent_name=self.skill_name,
            )

            persona_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)
            required_fields = {
                "reply_text",
                "emotion_state",
                "interview_stage",
                "is_completed",
                "used_experience_card_ids",
            }
            if not isinstance(persona_data, dict) or not required_fields.issubset(persona_data):
                raise ValueError("Persona LLM 返回结果缺少必需字段")
            if not str(persona_data["reply_text"]).strip():
                raise ValueError("Persona LLM 返回了空回复")
            used_ids = persona_data.get("used_experience_card_ids")
            if not isinstance(used_ids, list) or any(not isinstance(item, str) for item in used_ids):
                raise ValueError("Persona LLM 返回了无效的经验引用列表")
            allowed_ids = {
                str(reference["source_id"])
                for reference in experience_references
            }
            if set(used_ids) != allowed_ids or len(used_ids) != len(allowed_ids):
                raise ValueError("Persona LLM 未严格使用已授权的经验引用")

            reply_text = str(persona_data["reply_text"]).strip()
            disclosure = (
                "以上建议由企业运营助手基于已发布并授权的专家经验生成，"
                "非专家本人实时回复。"
            )
            if experience_references and "非专家本人实时回复" not in reply_text:
                reply_text = f"{reply_text}\n\n{disclosure}"

            return SkillOutput(
                success=True,
                reply_text=reply_text,
                structured_data={
                    "emotion_state": persona_data["emotion_state"],
                    "interview_stage": persona_data["interview_stage"],
                    "is_completed": persona_data["is_completed"],
                    "response_mode": response_mode,
                    "used_experience_card_ids": used_ids,
                    "experience_references": experience_references,
                    "ai_generated": True,
                    "expert_live_reply": False,
                    "action_taken": "authorized_experience_synthesis",
                },
                action_taken="authorized_experience_synthesis",
                tokens_used=llm_res.tokens_used,
            )

        except KeyError as e:
            logger.error(f"[Trace-{trace_id}] Persona Prompt 格式化失败，可能是由于 JSON 的 {{}} 未转义导致: {e}")
            raise
        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Persona 交互引擎执行异常: {e}")
            raise
