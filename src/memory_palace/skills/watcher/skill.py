"""
鹰眼巡检专家智能体 (Watcher Skill Implementation) - 异步版本

核心变更：
1. 核心执行方法添加 async/await
2. 调用 llm_client 的地方添加 await
3. 文件 IO 保持同步 (磁盘读写快，无需异步)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill

try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，Watcher 将以模拟模式运行")
    llm_client = None


@register_skill("watcher")
class WatcherSkill(BaseAgentSkill):
    """
    鹰眼巡检专家：负责后台定时巡检、SOP 合规性审查与超时工单追办 (异步版本)。
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()

        super().__init__(
            skill_name=self.config.get("agent_name", "Watcher_Audit_Agent"),
            model_name=self.config.get("llm_config", {}).get("model", "gpt-4-turbo")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载鹰眼专属的运行时配置"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("Watcher config 缺失，采用默认审计参数。")
            return {
                "agent_name": "Watcher_Audit_Agent",
                "llm_config": {"model": "gpt-4-turbo", "temperature": 0.1}
            }

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_prompt_template(self) -> str:
        """加载巡检审计规则 Prompt (对应项目树中的 audit.txt)"""
        prompt_path = self.base_path / "prompts" / "audit.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"致命错误：未找到鹰眼审计模板 {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """巡检专家的入参契约：必须提供待审计的数据源集合 (audit_target_logs)"""
        if "audit_target_logs" not in context or not isinstance(context["audit_target_logs"], list):
            raise SkillValidationError("Watcher 需要 'audit_target_logs' 数组来进行批量审查。")

    def _format_audit_data(self, logs: List[Dict[str, Any]]) -> str:
        """
        工业级数据清洗与格式化：
        将数据库查出的原始 JSON 日志清洗成大模型易读的 Markdown 文本，防止 Token 浪费。
        """
        if not logs:
            return "【当前巡检周期内无待处理的日志】"

        formatted_str = ""
        for idx, log in enumerate(logs, 1):
            formatted_str += f"### 记录项 {idx} | 案卷号: {log.get('case_id', '未知')}\n"
            formatted_str += f"- 初始等级: {log.get('severity', '未知')}\n"
            formatted_str += f"- 指挥官下发指令: {log.get('dispatched_instruction', '无')}\n"
            formatted_str += f"- 一线员工反馈流: {log.get('employee_replies', '未反馈')}\n"
            formatted_str += f"- 距今耗时: {log.get('elapsed_minutes', 0)} 分钟\n\n"

        return formatted_str.strip()

    ### CHANGE: 核心方法改为 async
    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """执行定时巡检与审计逻辑 (异步版本)"""
        audit_logs = context.get("audit_target_logs", [])

        logger.info(f"[Trace-{trace_id}] Watcher 启动定时巡检 | 待审记录数: {len(audit_logs)}")

        # 容错：如果没有需要审计的日志，直接返回成功，不调用 LLM 浪费钱
        if not audit_logs:
            return SkillOutput(
                success=True,
                reply_text=None,
                structured_data={"audit_result": "pass", "escalations": []},
                action_taken="skip_empty_audit"
            )

        try:
            # 1. 组装待审计上下文
            formatted_logs = self._format_audit_data(audit_logs)

            # 2. 动态渲染审计 Prompt
            template = self._load_prompt_template()
            full_system_prompt = template.format(audit_logs=formatted_logs)

            if llm_client:
                # 3. 调用 LLM 进行审查
                llm_params = self.config.get("llm_config", {})

                ### CHANGE: 添加 await 调用异步 LLM
                llm_res = await llm_client.ask(
                    system_prompt=full_system_prompt,
                    user_prompt="请严格按照 SOP 规则，对上述记录进行合规性审计，并输出 JSON 报告。",
                    model=self.model_name,
                    temperature=llm_params.get("temperature", 0.1),
                    json_mode=True,
                    trace_id=trace_id
                )

                # 4. 解析审计报告
                ### CHANGE: 添加 await 调用异步解析
                audit_report = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

                # 提取是否需要触发警报 (Escalation)
                escalations = audit_report.get("escalated_cases", [])
                is_violation_found = len(escalations) > 0

                if is_violation_found:
                    logger.warning(f"[Trace-{trace_id}] Watcher 发现 {len(escalations)} 起违规/超时未闭环事件！")

                return SkillOutput(
                    success=True,
                    reply_text=audit_report.get("summary_message"),
                    structured_data={
                        "is_violation_found": is_violation_found,
                        "escalated_cases": escalations,
                        "audit_score": audit_report.get("audit_score", 100),
                        "action_taken": "sop_compliance_audit"
                    },
                    action_taken="sop_compliance_audit",
                    tokens_used=llm_res.tokens_used
                )
            else:
                return SkillOutput(
                    success=True,
                    reply_text="鹰眼巡检暂时离线，请稍后再试。",
                    structured_data={
                        "is_violation_found": False,
                        "escalated_cases": [],
                        "audit_score": 100,
                        "action_taken": "mock_sop_audit"
                    },
                    action_taken="mock_sop_audit"
                )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Watcher 审计引擎执行异常: {e}")
            raise
