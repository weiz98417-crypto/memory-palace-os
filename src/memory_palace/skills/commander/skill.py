"""
现场指挥官智能体 (Commander Skill Implementation) - 异步版本

核心变更：
1. 核心执行方法添加 async/await
2. 调用 llm_client 的地方添加 await
3. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，Commander 将以模拟模式运行")
    llm_client = None


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
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4o")
        )

    def _load_config(self) -> Dict[str, Any]:
        """工业级 YAML 加载：支持默认值回退"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning(f"Commander config 缺失，使用安全默认值。")
            return {"agent_metadata": {"name": "Commander_Agent"}, "llm_config": {"model": "gpt-4o"}}

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

            if llm_client:
                full_system_prompt = template.format(
                    severity=context.get("severity", "P3"),
                    summary=context.get("summary", ""),
                    raw_text=context.get("raw_text")
                )

                llm_params = self.config.get("llm_config", {})

                ### CHANGE: 添加 await 调用异步 LLM
                llm_res = await llm_client.ask(
                    system_prompt=full_system_prompt,
                    user_prompt=f"现场情况汇报：{context['raw_text']}",
                    model=self.model_name,
                    temperature=llm_params.get("temperature", 0.2),
                    json_mode=True,
                    trace_id=trace_id
                )

                ### CHANGE: 添加 await 调用异步解析
                dispatch_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

                final_reply = dispatch_data.get("reply_text")
                if not final_reply and context.get("severity") in ["P0", "P1"]:
                    final_reply = "【紧急提醒】现场情况危急，请立即拨打120，疏散人群，并保持电话通畅，等待值班经理到达！"

                return SkillOutput(
                    success=True,
                    reply_text=final_reply,
                    structured_data={
                        "dispatch_action": dispatch_data.get("action_taken"),
                        "next_step_check": dispatch_data.get("next_step_check"),
                        "required_tools": dispatch_data.get("required_tools", [])
                    },
                    action_taken="emergency_response_dispatch",
                    tokens_used=llm_res.tokens_used
                )
            else:
                final_reply = self._generate_mock_reply(context.get("severity", "P3"), context.get("raw_text"))
                return SkillOutput(
                    success=True,
                    reply_text=final_reply,
                    structured_data={
                        "dispatch_action": "mock_emergency_response",
                        "next_step_check": "请确认是否已执行",
                        "required_tools": []
                    },
                    action_taken="mock_dispatch"
                )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Commander 执行链崩溃: {e}")
            raise

    def _generate_mock_reply(self, severity: str, raw_text: str) -> str:
        """模拟回复生成 (纯 CPU 计算，无需 async)"""
        if severity == "P0":
            return f"【P0 紧急指令】\n\n立即拨打120并通知总值班室！\n\n请确认：是否已拨打120？"
        elif severity == "P1":
            return f"【P1 高危指令】\n\n立即通知工程部和安保部！\n\n请确认：相关人员是否已出发？"
        elif severity == "P2":
            return f"【P2 一般指令】\n\n请引导游客至服务中心并拍照记录。\n\n请确认：是否已完成拍照？"
        else:
            return f"【P3 咨询指令】\n\n已记录您的问题，我们将尽快处理。"
