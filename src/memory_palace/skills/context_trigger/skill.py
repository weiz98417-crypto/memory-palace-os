"""
情境触发专家智能体 (Context Trigger Skill Implementation)

对应 docx 中描述的两阶段事件触发系统：
- Stage1: 关键词预过滤（O(n) 字符串扫描，无 LLM 调用）
- Stage2: LLM 语义判断（仅对 Stage1 命中的消息调用）

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import time
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

from ...core.skill_base import BaseAgentSkill, SkillOutput, SkillValidationError
from .. import register_skill
from .keywords import KeywordMatcher


try:
    from ...tools.llm_wrapper import llm_client
except ImportError:
    logger.warning("llm_client 尚未实现，ContextTrigger 将以关键词模式运行")
    llm_client = None


@register_skill("context_trigger")
class ContextTriggerSkill(BaseAgentSkill):
    """
    情境触发专家：负责对消息进行两阶段判断。

    Stage1（关键词极速预过滤）：
      - 使用 TRIGGER_KEYWORDS 和 EXCLUDE_KEYWORDS 进行 O(n) 扫描
      - 命中 EXCLUDE_KEYWORDS → 直接跳过
      - 命中 TRIGGER_KEYWORDS → 进入 Stage2

    Stage2（LLM 语义判断）：
      - 仅对 Stage1 触发或 fallback 的消息进行 LLM 判断
      - 决定是否触发处置流程
    """

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.config = self._load_config()
        self._matcher: Optional[KeywordMatcher] = None

        super().__init__(
            skill_name=self.config.get("agent_metadata", {}).get("name", "ContextTrigger_Skill"),
            model_name=self.config.get("stage2_config", {}).get("llm_config", {}).get("model", "gpt-4o-mini")
        )

    def _load_config(self) -> Dict[str, Any]:
        """加载运行时配置"""
        config_path = self.base_path / "config.yaml"
        if not config_path.exists():
            logger.warning("ContextTrigger config 缺失，采用默认参数。")
            return {
                "agent_metadata": {"name": "ContextTrigger_Skill"},
                "scenic_types": [],
                "stage1_config": {"enable_extended_keywords": True},
                "stage2_config": {"enabled": True, "fallback_to_llm": True}
            }

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _get_matcher(self) -> KeywordMatcher:
        """懒加载关键词匹配器（避免重复初始化）"""
        if self._matcher is None:
            scenic_types = self.config.get("scenic_types", [])
            enable_extended = self.config.get("stage1_config", {}).get("enable_extended_keywords", True)
            self._matcher = KeywordMatcher(
                include_scenic_types=scenic_types,
                enable_extended=enable_extended
            )
        return self._matcher

    def _load_prompt_template(self) -> str:
        """加载 Stage2 LLM 判断 Prompt"""
        prompt_path = self.base_path / "prompts" / "trigger.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"致命错误：未找到情境判断模板 {prompt_path}")

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _validate_context(self, context: Dict[str, Any]) -> None:
        """ContextTrigger 的入参契约：必须提供 raw_text"""
        if "raw_text" not in context or not str(context["raw_text"]).strip():
            raise SkillValidationError("ContextTrigger 需要 'raw_text' 字段。")

    async def _execute_impl(self, context: Dict[str, Any], trace_id: str) -> SkillOutput:
        """
        执行两阶段判断逻辑

        Args:
            context: 包含 raw_text, from_user, timestamp 等字段
            trace_id: 追踪 ID

        Returns:
            SkillOutput，structured_data 中包含：
            - stage1_result: Stage1 匹配结果
            - stage2_result: Stage2 LLM 判断结果（如果有）
            - should_trigger: 是否应该触发处置流程
        """
        raw_text = str(context.get("raw_text", "")).strip()
        from_user = context.get("from_user", "unknown")
        timestamp = context.get("timestamp", time.time())

        logger.info(f"[Trace-{trace_id}] ContextTrigger 启动 | 文本长度: {len(raw_text)}")

        # ================================================================
        # Stage1: 关键词极速预过滤
        # ================================================================
        matcher = self._get_matcher()
        stage1_result = matcher.match(raw_text)

        logger.info(
            f"[Trace-{trace_id}] Stage1 匹配结果: "
            f"excluded={stage1_result['excluded']}, "
            f"triggered={stage1_result['triggered']}, "
            f"命中关键词={stage1_result['hit_keywords']}"
        )

        # 如果被排除，直接返回不处理
        if stage1_result["excluded"]:
            return SkillOutput(
                success=True,
                reply_text=None,
                structured_data={
                    "stage": "stage1",
                    "stage1_result": stage1_result,
                    "should_trigger": False,
                    "action": "excluded_by_keyword"
                },
                action_taken="stage1_keyword_exclude"
            )

        # ================================================================
        # Stage2: LLM 语义判断
        # ================================================================
        stage2_config = self.config.get("stage2_config", {})
        stage2_enabled = stage2_config.get("enabled", True)
        fallback_to_llm = stage2_config.get("fallback_to_llm", True)

        should_go_to_stage2 = stage1_result["triggered"] or fallback_to_llm

        if not stage2_enabled or not should_go_to_stage2:
            # Stage2 禁用或不需要执行
            return SkillOutput(
                success=True,
                reply_text=None,
                structured_data={
                    "stage": "stage1_only",
                    "stage1_result": stage1_result,
                    "should_trigger": False,
                    "action": "bypassed_stage2"
                },
                action_taken="stage1_trigger_no_stage2"
            )

        # 调用 LLM 进行语义判断
        return await self._do_stage2_judgment(
            raw_text=raw_text,
            stage1_result=stage1_result,
            from_user=from_user,
            timestamp=timestamp,
            trace_id=trace_id
        )

    async def _do_stage2_judgment(
        self,
        raw_text: str,
        stage1_result: Dict[str, Any],
        from_user: str,
        timestamp: float,
        trace_id: str
    ) -> SkillOutput:
        """执行 Stage2 LLM 判断"""
        logger.debug(f"[Trace-{trace_id}] Stage2 启动：调用 LLM 进行语义判断...")

        # 优先加载 push_logger（延迟导入避免循环）
        push_logger = None
        try:
            from ...knowledge.push_logger import write_push_log
            push_logger = write_push_log
        except Exception:
            pass

        if not llm_client:
            # 无 LLM 客户端时的兜底逻辑
            should_trigger = stage1_result["triggered"]
            event_type = "其他"
            severity = "P3/P4"
            confidence = 0.5

            # 写入推送日志
            if push_logger:
                await self._safe_push_log(
                    push_logger, None, from_user, raw_text,
                    event_type, severity, stage1_result, False, confidence, trace_id
                )

            # 触发推送 + 确认卡片
            if should_trigger:
                await self._trigger_wechat_push(from_user, raw_text, event_type, severity, trace_id)

            return SkillOutput(
                success=True,
                reply_text=None,
                structured_data={
                    "stage": "stage2_mock",
                    "stage1_result": stage1_result,
                    "should_trigger": should_trigger,
                    "stage2_result": {
                        "trigger": should_trigger,
                        "confidence": confidence,
                        "reason": "mock_mode_no_llm",
                        "event_type": event_type,
                        "severity": severity
                    }
                },
                action_taken="stage2_mock"
            )

        try:
            # 组装 Prompt
            system_prompt = self._load_prompt_template()

            # 格式化关键词命中信息
            keyword_hits_str = ""
            if stage1_result["hit_keywords"]:
                categories = stage1_result["hit_categories"]
                keywords = stage1_result["hit_keywords"]
                keyword_hits_str = "\n".join([f"- {kw}（{cat}）" for kw, cat in zip(keywords, categories)])

            # 上下文信息放入 user_prompt（遵循 Router 的模式）
            user_prompt = f"""### Stage1 关键词命中信息 (KEYWORD HITS)
{keyword_hits_str or "无"}

### 原始消息 (RAW MESSAGE)
{raw_text}

### 额外上下文 (CONTEXT)
- 发送者: {from_user}
- 消息时间: {timestamp}

请根据上述信息进行判断，返回 JSON 格式结果。"""

            llm_params = self.config.get("stage2_config", {}).get("llm_config", {})

            llm_res = await llm_client.ask(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model_name,
                temperature=llm_params.get("temperature", 0.0),
                max_tokens=llm_params.get("max_tokens", 500),
                json_mode=True,
                trace_id=trace_id
            )

            stage2_result = await llm_client.parse_json(llm_res.content, trace_id=trace_id)

            # 消毒 stage2_result
            from ...tools.llm_wrapper import sanitize_llm_output, ALLOWED_SEVERITIES
            stage2_result, _ = sanitize_llm_output(stage2_result, "stage2_result", trace_id=trace_id)

            # 额外校验 severity 白名单
            severity = stage2_result.get("severity", "P3")
            if severity not in ALLOWED_SEVERITIES:
                logger.warning(f"[Trace-{trace_id}] invalid severity '{severity}' — fallback to P3")
                severity = "P3"

            should_trigger = stage2_result.get("trigger", False)
            event_type = stage2_result.get("event_type", "其他")
            confidence = stage2_result.get("confidence", 0.0)

            logger.info(
                f"[Trace-{trace_id}] Stage2 判断完成: "
                f"trigger={should_trigger}, "
                f"severity={severity}, "
                f"reason={stage2_result.get('reason', 'N/A')}"
            )

            # 写入推送日志
            if push_logger:
                await self._safe_push_log(
                    push_logger, None, from_user, raw_text,
                    event_type, severity, stage1_result, True, confidence, trace_id
                )

            # 触发 WeChat 推送 + 延迟确认卡片
            if should_trigger:
                await self._trigger_wechat_push(from_user, raw_text, event_type, severity, trace_id)

            return SkillOutput(
                success=True,
                reply_text=None,
                structured_data={
                    "stage": "stage2",
                    "stage1_result": stage1_result,
                    "stage2_result": stage2_result,
                    "should_trigger": should_trigger,
                    "severity": severity,
                    "event_type": event_type,
                    "confidence": confidence
                },
                action_taken="stage2_llm_judgment",
                tokens_used=llm_res.tokens_used
            )

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Stage2 LLM 判断异常: {e}")
            # LLM 异常时，保守策略：不触发
            return SkillOutput(
                success=False,
                reply_text=None,
                structured_data={
                    "stage": "stage2_error",
                    "stage1_result": stage1_result,
                    "should_trigger": False,
                    "error": str(e)
                },
                action_taken="stage2_error_fallback"
            )

    async def _safe_push_log(
        self,
        write_push_log_fn,
        msg_id: Optional[str],
        from_user: str,
        raw_text: str,
        event_type: str,
        severity: str,
        stage1_result: Dict[str, Any],
        stage2_triggered: bool,
        llm_confidence: float,
        trace_id: str,
    ) -> None:
        """安全写入推送日志（异常不阻断主流程）"""
        try:
            await write_push_log_fn(
                msg_id=msg_id or "",
                from_user=from_user,
                raw_text=raw_text,
                event_type=event_type,
                severity=severity,
                stage1_triggered=stage1_result.get("triggered", False),
                hit_keywords=stage1_result.get("hit_keywords", []),
                stage2_triggered=stage2_triggered,
                llm_confidence=llm_confidence,
                trace_id=trace_id,
            )
        except Exception as e:
            logger.warning(f"[Trace-{trace_id}] 推送日志写入失败: {e}")

    async def _trigger_wechat_push(
        self,
        from_user: str,
        raw_text: str,
        event_type: str,
        severity: str,
        trace_id: str,
    ) -> None:
        """
        触发 WeChat 推送 + 延迟确认卡片

        流程：
        1. 立即发送事件推送卡片
        2. 延迟 confirm_delay_seconds 后发送确认卡片
        """
        try:
            from ...tools.wechat_client import get_wechat_client
        except ImportError:
            logger.warning("wechat_client 未导入，跳过 WeChat 推送")
            return

        wc = get_wechat_client()
        if not wc:
            logger.warning("wechat_client 未初始化，跳过 WeChat 推送")
            return

        confirm_card_cfg = self.config.get("confirm_card", {})
        confirm_delay = self.config.get("confirm_delay_seconds", 180)

        # 生成推送卡片内容
        push_title = f"🚨 [{severity}] {event_type}事件"
        push_desc = raw_text[:100] + ("..." if len(raw_text) > 100 else "")

        # 1. 立即发送事件推送
        push_ok = await wc.send_textcard(
            to_user=from_user,
            title=push_title,
            description=push_desc,
            url=os.getenv("CT_PUSH_URL", "http://localhost:8000/admin"),
            btntxt="查看详情",
        )

        if push_ok:
            logger.info(f"[Trace-{trace_id}] 事件推送卡片已发送: to={from_user}")
        else:
            logger.warning(f"[Trace-{trace_id}] 事件推送卡片发送失败: to={from_user}")

        # 2. 延迟发送确认卡片（asyncio task，不阻塞）
        if confirm_card_cfg.get("enabled", True):
            import asyncio
            asyncio.create_task(
                self._send_delayed_confirm_card(
                    to_user=from_user,
                    event_summary=f"[{severity}] {event_type} - {raw_text[:20]}",
                    event_type=event_type,
                    severity=severity,
                    delay_seconds=confirm_delay,
                    trace_id=trace_id,
                )
            )

    async def _send_delayed_confirm_card(
        self,
        to_user: str,
        event_summary: str,
        event_type: str,
        severity: str,
        delay_seconds: int,
        trace_id: str,
    ) -> None:
        """
        延迟发送确认卡片（协程任务）

        Args:
            delay_seconds: 延迟秒数
        """
        import asyncio
        await asyncio.sleep(delay_seconds)

        try:
            from ...tools.wechat_client import get_wechat_client
        except ImportError:
            return

        wc = get_wechat_client()
        if not wc:
            return

        # 构建确认卡片内容（使用交互卡片 URL 模式）
        base_url = os.getenv("CT_CALLBACK_URL", "http://localhost:8000/webhook/v1/callback")
        confirm_url = f"{base_url}/confirm?user={to_user}&action=confirm"
        supplement_url = f"{base_url}/confirm?user={to_user}&action=supplement"

        ok = await wc.send_confirm_card(
            to_user=to_user,
            push_id="",  # push_id 由回调时传入
            event_summary=event_summary,
            event_type=event_type,
            severity=severity,
            confirm_url=confirm_url,
            supplement_url=supplement_url,
        )

        if ok:
            logger.info(f"[Trace-{trace_id}] 确认卡片已发送: to={to_user}, delay={delay_seconds}s")
        else:
            logger.warning(f"[Trace-{trace_id}] 确认卡片发送失败: to={to_user}")
