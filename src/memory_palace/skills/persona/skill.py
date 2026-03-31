"""
知识分身专家智能体 (Persona Skill Implementation) - 异步版本

核心变更：
1. 核心执行方法添加 async/await
2. 调用 llm_client 的地方添加 await
3. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import yaml
import json
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，Persona 将以模拟模式运行")
    llm_client = None


@register_skill("persona")
class PersonaSkill(BaseAgentSkill):
    """
    知识分身专家：负责深度的拟人化交互、模拟面试审查或复杂政策咨询 (异步版本)。
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_name", "Persona_Expert_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4o")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载分身专属的运行时配置"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("Persona config 缺失，采用默认对话参数。")
            return {
                "agent_name": "Persona_Expert_Agent",
                "llm_config": {"model": "gpt-4o", "temperature": 0.5},
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
        """分身专家入参校验"""
        if "raw_text" not in context or not str(context["raw_text"]).strip():
            raise SkillValidationError("Persona 缺少用户输入的 'raw_text'。")

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
            role_name = "员工" if msg.get("role") == "user" else "专家"
            content = msg.get("content", "").replace("\n", " ")
            formatted_str += f"[{role_name}]: {content}\n"

        return formatted_str.strip()

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """执行分身深度交互逻辑 (异步版本)"""
        query_text = str(context["raw_text"]).strip()
        chat_history = context.get("history", [])

        logger.info(f"[Trace-{trace_id}] Persona 启动深度交互 | 历史轮数: {len(chat_history)}")

        try:
            # 1. 组装历史上下文
            formatted_history = self._format_history_window(chat_history)

            # 2. 动态渲染系统级 Prompt
            template = self._load_prompt_template()
            full_system_prompt = template.format(chat_history=formatted_history)

            if llm_client:
                # 3. 调用 LLM
                llm_params = self.config.get("llm_config", {})

                ### CHANGE: 添加 await 调用异步 LLM
                llm_res = await llm_client.ask(
                    system_prompt=full_system_prompt,
                    user_prompt=f"员工最新回复：{query_text}",
                    model=self.model_name,
                    temperature=llm_params.get("temperature", 0.5),
                    json_mode=True,
                    trace_id=trace_id
                )

                # 4. 解析大模型返回的复合 JSON
                ### CHANGE: 添加 await 调用异步解析
                persona_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

                # 工业级容错
                reply_text = persona_data.get("reply_text")
                if not reply_text:
                    logger.warning(f"[Trace-{trace_id}] Persona 模型未返回 reply_text 字段，触发安全降级。")
                    reply_text = "抱歉，我正在思考您的诉求，请您稍后重新描述。"
                    persona_data["reply_text"] = reply_text

                return SkillOutput(
                    success=True,
                    reply_text=reply_text,
                    structured_data={
                        "emotion_state": persona_data.get("emotion_state", "neutral"),
                        "interview_stage": persona_data.get("interview_stage", "ongoing"),
                        "is_completed": persona_data.get("is_completed", False),
                        "action_taken": "persona_deep_interaction"
                    },
                    action_taken="persona_deep_interaction",
                    tokens_used=llm_res.tokens_used
                )
            else:
                return SkillOutput(
                    success=True,
                    reply_text="分身专家暂时离线，请稍后再试。",
                    structured_data={
                        "emotion_state": "neutral",
                        "interview_stage": "mock",
                        "is_completed": False,
                        "action_taken": "mock_persona_interaction"
                    },
                    action_taken="mock_persona_interaction"
                )

        except KeyError as e:
            logger.error(f"[Trace-{trace_id}] Persona Prompt 格式化失败，可能是由于 JSON 的 {{}} 未转义导致: {e}")
            raise
        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Persona 交互引擎执行异常: {e}")
            raise
