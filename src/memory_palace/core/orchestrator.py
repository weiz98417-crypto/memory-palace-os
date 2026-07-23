"""
orchestrator.py · 多智能体协作中枢
================================================================
负责协调多个 Agent 完成任务流转

[升级] Phase 1:
- Scoped Context: Router 输出仅作为分发元数据，不原封传递给下游
- Agent Memory Isolation: 每个 Agent 只看到自己的对话历史
"""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from src.memory_palace.skills import get_skill_by_name
from src.memory_palace.core.container import AppContainer, container as _default_container


class Orchestrator:
    """
    多智能体协作中枢
    负责协调 Router、Commander、MemoryOps、Persona 等 Agent

    [M2] 接受 AppContainer 参数，支持依赖注入测试。
    """

    def __init__(self, use_scoped_context: bool = False,
                 container: Optional[AppContainer] = None):
        self.context: Dict[str, Any] = {}
        self.use_scoped_context = use_scoped_context
        self.container = container or _default_container

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理消息

        Args:
            payload: 消息载荷

        Returns:
            处理结果
        """
        msg_id = payload.get("msg_id", "unknown")
        trace_id = payload.get("trace_id", "")

        logger.info(f"[Trace-{trace_id}] 🎭 [Orchestrator] 开始处理消息 {msg_id}")

        # 1. 保存消息到数据库
        await self._save_message(payload)

        # 2. 路由决策
        route_result = await self._route(payload)

        # ContextTrigger 排除的消息直接跳过
        if route_result and route_result.get("status") == "bypassed":
            logger.info(
                f"[Trace-{trace_id}] 🎭 [Orchestrator] 消息被 ContextTrigger 排除，跳过处理"
            )
            return {
                "status": "bypassed",
                "route": route_result,
                "agent_result": None,
            }

        if not route_result or route_result.get("status") != "routed":
            logger.warning(f"[Trace-{trace_id}] 路由失败，使用默认处理")
            route_result = await self._default_route(payload)

        # 3. 执行目标 Agent
        agent_result = await self._execute_agent(route_result)

        # 4. 更新 SLA 记录
        if route_result.get("priority") in ["P0", "P1"]:
            await self._update_sla_response(msg_id)

        logger.info(
            f"[Trace-{trace_id}] 🎭 [Orchestrator] 处理完成 "
            f"[Agent={route_result.get('target_agent')}]"
        )

        return {
            "status": "processed",
            "route": route_result,
            "agent_result": agent_result,
            "reply_text": getattr(agent_result, "reply_text", None) if agent_result else None,
            "trace_id": trace_id,
        }

    async def _save_message(self, payload: Dict[str, Any]):
        """保存消息到数据库"""
        try:
            from src.memory_palace.knowledge.db_client import save_message, create_or_update_session
            await save_message(payload)
            from_user = payload.get("from_user", "unknown")
            await create_or_update_session(from_user)
        except Exception as e:
            logger.error(f"❌ 保存消息失败: {e}")

    async def _route(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        路由决策

        集成 ContextTrigger 两阶段过滤：
        1. 先调用 ContextTrigger 进行 Stage1 关键词预过滤
        2. 根据结果决定：
           - 被排除 → 跳过处理
           - 应触发 → 直接路由到 Commander（突发事件处置）
           - 其他 → 继续 Router 正常路由

        Args:
            payload: 消息载荷

        Returns:
            路由结果
        """
        msg_id = payload.get("msg_id", "unknown")
        trace_id = payload.get("trace_id", "")
        raw_text = payload.get("content", "")

        try:
            # ================================================================
            # 阶段 0: ContextTrigger 前置过滤（可选）
            # ================================================================
            context_trigger = get_skill_by_name("context_trigger")

            if context_trigger:
                try:
                    ct_context = {
                        "raw_text": raw_text,
                        "from_user": payload.get("from_user", "unknown"),
                        "timestamp": payload.get("timestamp", 0),
                        "msg_id": msg_id
                    }
                    ct_result = await context_trigger.run(ct_context, trace_id=trace_id)

                    if ct_result.success and ct_result.structured_data:
                        sd = ct_result.structured_data
                        stage = sd.get("stage", "")

                        # Stage1 命中 EXCLUDE_KEYWORDS → 跳过
                        if sd.get("excluded"):
                            logger.info(
                                f"[Trace-{trace_id}] ContextTrigger Stage1 排除: "
                                f"关键词={sd.get('stage1_result', {}).get('hit_keywords', [])}"
                            )
                            return {
                                "status": "bypassed",
                                "bypass_reason": "context_trigger_excluded",
                                "hit_keywords": sd.get("stage1_result", {}).get("hit_keywords", []),
                                "target_agent": None,
                                "from_user": payload.get("from_user", "unknown"),
                                "content": raw_text,
                                "trace_id": trace_id,
                            }

                        # Stage2 判断应触发 → 直接路由到 Commander
                        if sd.get("should_trigger"):
                            severity = sd.get("severity", "P2")
                            event_type = sd.get("event_type", "其他")
                            logger.info(
                                f"[Trace-{trace_id}] ContextTrigger 触发处置: "
                                f"severity={severity}, event_type={event_type}"
                            )
                            return {
                                "status": "routed",
                                "intent": "incident_report",
                                "priority": severity,
                                "severity": severity,
                                "target_agent": "commander",
                                "from_user": payload.get("from_user", "unknown"),
                                "content": raw_text,
                                "msg_id": msg_id,
                                "trace_id": trace_id,
                                "context_trigger_data": {
                                    "stage": stage,
                                    "event_type": event_type,
                                    "confidence": sd.get("confidence", 0.0),
                                    "stage1_keywords": sd.get("stage1_result", {}).get("hit_keywords", []),
                                }
                            }

                except Exception as e:
                    logger.warning(f"[Trace-{trace_id}] ContextTrigger 执行异常，降级到 Router: {e}")
                    # ContextTrigger 异常时，继续走 Router

            # ================================================================
            # 阶段 1: Router 正常路由
            # ================================================================
            router = get_skill_by_name("router")
            if not router:
                logger.warning("⚠️ Router 技能未注册")
                return None

            # 传入 raw_text（Router._validate_context 要求此字段）
            context = {"raw_text": raw_text, "msg_id": msg_id}
            result = await router.run(context)

            # Router 返回的是 SkillOutput，需要提取 structured_data
            if hasattr(result, 'structured_data'):
                sd = result.structured_data
                return {
                    "status": "routed",
                    "intent": sd.get("intent", "other"),
                    "severity": sd.get("severity", "P3"),
                    "priority": sd.get("severity", "P3"),
                    "target_agent": self._intent_to_agent(sd.get("intent", "other")),
                    "from_user": payload.get("from_user", "unknown"),
                    "content": raw_text,
                    "msg_id": msg_id,
                    "trace_id": trace_id,
                    "router_confidence": sd.get("confidence", 0.0),
                }

            return result

        except Exception as e:
            logger.error(f"❌ 路由失败: {e}")
            return None

    def _intent_to_agent(self, intent: str) -> str:
        """
        将 intent 映射到目标 Agent

        Args:
            intent: Router 返回的 intent 类型

        Returns:
            目标 Agent 名称
        """
        intent_agent_map = {
            "incident_report": "commander",      # 突发事件 → 指挥官
            "emergency_dispatch": "commander",   # 紧急调度 → 指挥官
            "emergency_advice": "memory_ops",    # 应急经验检索 → 记忆专家
            "chitchat": "persona",              # 闲聊 → 人设专家
            "other": "persona",                 # 其他 → 人设专家
        }
        return intent_agent_map.get(intent, "persona")

    async def _default_route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        默认路由

        Args:
            payload: 消息载荷

        Returns:
            默认路由结果
        """
        return {
            "status": "routed",
            "intent": "routine",
            "priority": payload.get("priority", "P3"),
            "target_agent": "persona_extract",
            "from_user": payload.get("from_user", "unknown"),
            "content": payload.get("content", ""),
        }

    async def _execute_agent(
        self,
        route_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行目标 Agent

        [升级] 支持两种上下文模式:
        - legacy_mode: 原有的 flat context (向后兼容)
        - scoped_mode: 每个 Agent 仅收到必要字段，Router 输出作为分发元数据

        Args:
            route_result: 路由结果

        Returns:
            Agent 执行结果
        """
        target_agent = route_result.get("target_agent")
        trace_id = route_result.get("trace_id", "")
        session_id = route_result.get("session_id", "unknown")

        if not target_agent:
            logger.warning(f"[Trace-{trace_id}] 未指定目标 Agent")
            return {"status": "skipped", "reason": "no_target_agent"}

        try:
            skill = get_skill_by_name(target_agent)
            if not skill:
                logger.warning(f"[Trace-{trace_id}] Agent {target_agent} 未注册")
                return {"status": "skipped", "reason": "agent_not_found"}

            # 构建执行上下文
            if self.use_scoped_context:
                # [新] Scoped Context 模式
                scoped_builder = self.container.agent_memory

                context = scoped_builder.build_scoped_context(
                    agent_name=target_agent,
                    session_id=session_id,
                    base_context=route_result,
                    route_result=route_result
                )

                logger.debug(
                    f"[Trace-{trace_id}] [ScopedContext] {target_agent} receives: "
                    f"{list(context.keys())}"
                )
            else:
                # [Legacy] 原有 flat context
                context = {
                    "raw_text": route_result.get("content", ""),
                    "severity": route_result.get("severity", ""),
                    "from_user": route_result.get("from_user", "unknown"),
                    "msg_id": route_result.get("msg_id", ""),
                    "priority": route_result.get("priority", "P3"),
                    "intent": route_result.get("intent", "routine"),
                    "trace_id": trace_id,
                }

            # 执行技能
            result = await skill.run(context)

            # 如果是 scoped 模式，记录 Agent 交互
            if self.use_scoped_context:
                scoped_builder = self.container.agent_memory
                scoped_builder.record_agent_turn(
                    session_id=session_id,
                    agent_name=target_agent,
                    input_text=context.get("raw_text", ""),
                    output_text=result.get("reply_text") if hasattr(result, 'reply_text') else str(result),
                    structured_data=result.structured_data if hasattr(result, 'structured_data') else {},
                    tokens_used=result.tokens_used if hasattr(result, 'tokens_used') else 0
                )

            return result

        except Exception as e:
            logger.error(f"[Trace-{trace_id}] Agent {target_agent} 执行失败: {e}")
            return {"status": "failed", "error": str(e)}

    async def _update_sla_response(self, msg_id: str):
        """更新 SLA 响应时间"""
        try:
            from src.memory_palace.knowledge.db_client import update_sla_response

            await update_sla_response(msg_id)
            logger.info(f"✅ SLA 响应时间已记录: {msg_id}")

        except Exception as e:
            logger.error(f"❌ SLA 记录更新失败: {e}")

    async def dispatch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """派发消息（queue_worker 的入口）"""
        return await self.process(payload)

    async def agent_handoff(
        self,
        from_agent: str,
        to_agent: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Agent 之间的交接

        [升级] Scoped Context 模式下:
        - 记录 from_agent 的 turn 到其独立内存
        - to_agent 只收到 shared_context 中必要的字段

        Args:
            from_agent: 来源 Agent
            to_agent: 目标 Agent
            context: 交接上下文

        Returns:
            交接结果
        """
        logger.info(
            f"🔄 [Orchestrator] Agent 交接: {from_agent} -> {to_agent}"
        )

        session_id = context.get("session_id", "unknown")

        # 添加交接标记
        context["handoff_from"] = from_agent
        context["handoff_reason"] = context.get("handoff_reason", "task_complete")

        # 如果是 scoped 模式，先记录 from_agent 的 turn
        if self.use_scoped_context:
            scoped_builder = self.container.agent_memory
            scoped_builder.record_agent_turn(
                session_id=session_id,
                agent_name=from_agent,
                input_text=context.get("content", ""),
                output_text=context.get("output_text", ""),
                structured_data=context.get("structured_data", {}),
                tokens_used=context.get("tokens_used", 0)
            )

        # 执行目标 Agent
        result = await self._execute_agent({
            "target_agent": to_agent,
            "content": context.get("content", ""),
            "from_user": context.get("from_user", "unknown"),
            "trace_id": context.get("trace_id", ""),
            "session_id": session_id,
            **context,
        })

        return {
            "status": "handoff_complete",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "result": result,
        }

    