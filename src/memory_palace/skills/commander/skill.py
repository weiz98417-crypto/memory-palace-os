"""
现场指挥官智能体 (Commander Skill Implementation) - 异步版本

核心变更：
1. 核心执行方法添加 async/await
2. 调用 llm_client 的地方添加 await
3. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import yaml
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from ...tools.llm_wrapper import llm_client
from .. import register_skill


@register_skill("commander")
class CommanderSkill(BaseAgentSkill):
    """
    现场指挥官：负责突发事件 (incident_report) 的实时分派与处置建议 (异步版本)。
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_metadata", {}).get("name", "Commander_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "deepseek-flash")
        )

    def _load_config(self) -> Dict[str, Any]:
        """工业级 YAML 加载：支持默认值回退"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning(f"Commander config 缺失，使用安全默认值。")
            return {"agent_metadata": {"name": "Commander_Agent"}, "llm_config": {"model": "deepseek-flash"}}

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_prompt_template(self) -> str:
        """从 prompts/dispatch.txt 加载原始指令模板"""
        prompt_path = self.base_path / "prompts" / "dispatch.txt"
        if not prompt_path.exists():
            return "你是景区运营记忆宫殿的现场指挥官。"

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """指挥官准入契约：必须具备 Router 识别出的核心字段"""
        required_fields = ["severity", "raw_text"]
        missing = [f for f in required_fields if f not in context or not context[f]]

        if missing:
            raise SkillValidationError(f"Commander 缺少关键链路数据: {', '.join(missing)}")

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """执行突发事件处置逻辑 (异步版本)"""
        logger.info(f"[Trace-{trace_id}] Commander 启动 P 级处置流程 | 等级: {context['severity']}")

        try:
            template = self._load_prompt_template()

            if not llm_client:
                raise RuntimeError("Commander LLM 客户端未初始化，不能生成处置指令")

            full_system_prompt = template.format(
                severity=context.get("severity", "P3"),
                summary=context.get("summary", ""),
                raw_text=context.get("raw_text"),
                event_type=context.get("event_type", "待确认事件"),
                risk_reason=context.get("risk_reason", "尚无额外风险判断理由"),
                attachment_context=context.get("attachment_context", "未提供附件说明"),
                knowledge_context=context.get(
                    "knowledge_context",
                    "未找到已发布依据，不得构造 SOP、案例或专家经验引用。",
                ),
            )

            llm_params = self.config.get("llm_config", {})

            llm_res = await llm_client.ask(
                system_prompt=full_system_prompt,
                user_prompt=f"现场情况汇报：{context['raw_text']}",
                model=self.model_name,
                temperature=llm_params.get("temperature", 0.2),
                json_mode=True,
                trace_id=trace_id,
                venue_id=context.get("venue_id", ""),
                agent_id="Commander",
                agent_name=self.skill_name,
            )

            dispatch_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)
            required_fields = {"reply_text", "action_taken", "required_tools", "next_step_check"}
            if not isinstance(dispatch_data, dict) or not required_fields.issubset(dispatch_data):
                raise ValueError("Commander LLM 返回结果缺少必需字段")
            if not str(dispatch_data["reply_text"]).strip():
                raise ValueError("Commander LLM 返回了空处置指令")

            return SkillOutput(
                success=True,
                reply_text=dispatch_data["reply_text"],
                structured_data={
                    "dispatch_action": dispatch_data["action_taken"],
                    "next_step_check": dispatch_data["next_step_check"],
                    "required_tools": dispatch_data["required_tools"],
                    "risk_reason": dispatch_data.get("risk_reason") or context.get("risk_reason"),
                    "immediate_actions": dispatch_data.get("immediate_actions") or [],
                    "knowledge_references": context.get("knowledge_references") or [],
                },
                action_taken="emergency_response_dispatch",
                tokens_used=llm_res.tokens_used
            )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Commander 执行链崩溃: {e}")
            raise
