"""
orchestrator.py · 多智能体协作中枢
================================================================
负责协调多个 Agent 完成任务流转
"""

import asyncio
from typing import Any, Dict, Optional

from loguru import logger

from src.memory_palace.skills import get_skill_by_name


class Orchestrator:
    """
    多智能体协作中枢
    负责协调 Router、Commander、MemoryOps、Persona 等 Agent
    """

    def __init__(self):
        self.context: Dict[str, Any] = {}

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
        }

    async def _save_message(self, payload: Dict[str, Any]):
        """保存消息到数据库"""
        try:
            from src.memory_palace.knowledge.db_client import save_message, create_or_update_session

            await save_message(payload)

            # 创建或更新会话
            from_user = payload.get("from_user", "unknown")
            await create_or_update_session(from_user)

        except Exception as e:
            logger.error(f"❌ 保存消息失败: {e}")

    async def _route(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        路由决策

        Args:
            payload: 消息载荷

        Returns:
            路由结果
        """
        try:
            router = get_skill_by_name("router")
            if not router:
                logger.warning("⚠️ Router 技能未注册")
                return None

            # 传入 raw_text（Router._validate_context 要求此字段）
            context = {"raw_text": payload.get("content", ""), "msg_id": msg_id}
            result = await router.run(context)
            return result

        except Exception as e:
            logger.error(f"❌ 路由失败: {e}")
            return None

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
            "priority": "P3",
            "target_agent": "deep_interview",
            "from_user": payload.get("from_user", "unknown"),
            "content": payload.get("content", ""),
        }

    async def _execute_agent(
        self,
        route_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行目标 Agent

        Args:
            route_result: 路由结果

        Returns:
            Agent 执行结果
        """
        target_agent = route_result.get("target_agent")
        trace_id = route_result.get("trace_id", "")

        if not target_agent:
            logger.warning(f"[Trace-{trace_id}] 未指定目标 Agent")
            return {"status": "skipped", "reason": "no_target_agent"}

        try:
            skill = get_skill_by_name(target_agent)
            if not skill:
                logger.warning(f"[Trace-{trace_id}] Agent {target_agent} 未注册")
                return {"status": "skipped", "reason": "agent_not_found"}

            # 构建执行上下文
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

        # 添加交接标记
        context["handoff_from"] = from_agent
        context["handoff_reason"] = context.get("handoff_reason", "task_complete")

        # 执行目标 Agent
        result = await self._execute_agent({
            "target_agent": to_agent,
            "content": context.get("content", ""),
            "from_user": context.get("from_user", "unknown"),
            "trace_id": context.get("trace_id", ""),
            **context,
        })

        return {
            "status": "handoff_complete",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "result": result,
        }

    