"""
路由大管家智能体 (Router Skill Implementation) - 异步版本

核心变更：
1. 所有方法添加 async/await 前缀
2. 调用 llm_client 的地方添加 await
3. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，Router 将以模拟模式运行")
    llm_client = None


@register_skill("router")
class RouterSkill(BaseAgentSkill):
    """
    路由大管家：系统的意图分发与风险分诊中枢 (异步版本)。
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_name", "Router_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "gpt-3.5-turbo")
        )

        self.chitchat_patterns = [
            r"^(你好|在吗|早上好|下午好|哈喽|hi|hello)$",
            r"^(谢谢|辛苦了|收到|好的|ok|OK|1|2|3)$"
        ]

    def _load_config(self) -> Dict[str, Any]:
        """工业级配置加载：确保文件缺失时有安全默认值"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning(f"Router config 缺失，使用硬编码默认配置。")
            return {"agent_name": "Router_Agent", "llm_config": {"model": "gpt-3.5-turbo"}}

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_system_prompt(self) -> str:
        """从独立 txt 文件中读取 Prompt，实现业务与代码分离"""
        prompt_path = self.base_path / "prompts" / "router.txt"
        if not prompt_path.exists():
            return "你是一个景区运营智能助手路由大管家。"

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """准入校验：路由必须有原始文本"""
        if "raw_text" not in context or not str(context["raw_text"]).strip():
            raise SkillValidationError("路由请求缺少有效 'raw_text'。")

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        raw_text = str(context["raw_text"]).strip()

        # ---------------------------------------------------------
        # 阶段 1: L1 快速路径 (正则表达式拦截)
        # ---------------------------------------------------------
        for pattern in self.chitchat_patterns:
            if re.match(pattern, raw_text, re.IGNORECASE):
                logger.info(f"[Trace-{trace_id}] Router L1 命中：正则拦截闲聊内容")
                return SkillOutput(
                    success=True,
                    reply_text="你好！我是景区记忆宫殿管家，请问有什么可以帮您？",
                    structured_data={"intent": "chitchat", "severity": "P4"},
                    action_taken="l1_regex_interception"
                )

        # ---------------------------------------------------------
        # 阶段 2: L2 深度路径 (大模型语义分析)
        # ---------------------------------------------------------
        logger.debug(f"[Trace-{trace_id}] Router L2 启动：调用 LLM 进行语义分诊...")

        try:
            system_prompt = self._load_system_prompt()

            if llm_client:
                llm_params = self.config.get("llm_config", {})

                ### CHANGE: 添加 await 调用异步 LLM
                llm_res = await llm_client.ask(
                    system_prompt=system_prompt,
                    user_prompt=raw_text,
                    model=self.model_name,
                    temperature=llm_params.get("temperature", 0.1),
                    json_mode=True,
                    trace_id=trace_id
                )

                ### CHANGE: 添加 await 调用异步解析
                intent_data = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

                if not intent_data:
                    intent_data = {"intent": "other", "severity": "P3", "summary": "未知意图"}

                return SkillOutput(
                    success=True,
                    reply_text=None,
                    structured_data=intent_data,
                    action_taken="llm_semantic_analysis",
                    tokens_used=llm_res.tokens_used
                )
            else:
                return SkillOutput(
                    success=True,
                    reply_text=None,
                    structured_data={"intent": "other", "severity": "P3", "summary": "模拟模式"},
                    action_taken="mock_analysis"
                )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Router L2 执行异常: {e}")
            raise
