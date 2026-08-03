"""
orchestrator.py · 多智能体协作中枢
================================================================
负责协调多个 Agent 完成任务流转

[升级] Phase 1:
- Scoped Context: Router 输出仅作为分发元数据，不原封传递给下游
- Agent Memory Isolation: 每个 Agent 只看到自己的对话历史
"""

import asyncio
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

from loguru import logger

from src.memory_palace.skills import get_skill_by_name
from src.memory_palace.core.business_ids import build_business_id
from src.memory_palace.core.container import AppContainer, container as _default_container
from src.memory_palace.core.event_activities import append_event_activity
from src.memory_palace.core.experience_usage import (
    ExperienceUsageContext,
    ExperienceUsageLedger,
    ExperienceUsagePersistenceError,
)


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
        agent_trace = route_result.get("agent_trace", []) if isinstance(route_result, dict) else []

        # ContextTrigger 排除的消息直接跳过
        if route_result and route_result.get("status") == "bypassed":
            logger.info(
                f"[Trace-{trace_id}] 🎭 [Orchestrator] 消息被 ContextTrigger 排除，跳过处理"
            )
            return {
                "status": "bypassed",
                "route": route_result,
                "agent_result": None,
                "agent_trace": agent_trace,
                "trace_id": trace_id,
            }

        if route_result and route_result.get("status") == "failed":
            return {
                "status": "failed",
                "route": route_result,
                "agent_result": None,
                "reply_text": route_result.get("reply_text"),
                "error": route_result.get("error") or "Routing failed",
                "trace_id": trace_id,
                "agent_trace": agent_trace,
            }

        if route_result and route_result.get("status") == "responded":
            return {
                "status": "processed",
                "route": route_result,
                "agent_result": None,
                "knowledge_result": None,
                "reply_text": route_result.get("reply_text"),
                "trace_id": trace_id,
                "agent_trace": agent_trace,
                "event_id": None,
                "business_cards": [],
            }

        if not route_result or route_result.get("status") != "routed":
            logger.warning(f"[Trace-{trace_id}] 路由结果不可执行，按失败关闭")
            route_result = await self._default_route(payload)
            agent_trace = route_result["agent_trace"]
            return {
                "status": "failed",
                "route": route_result,
                "agent_result": None,
                "reply_text": route_result.get("reply_text"),
                "error": route_result.get("error") or "Routing failed",
                "trace_id": trace_id,
                "agent_trace": agent_trace,
            }

        # 3. 事故链先检索已发布依据，再由 Commander 生成受引用约束的处置建议。
        knowledge_result = None
        experience_persona_result = None
        references: list[Dict[str, Any]] = []
        experience_references: list[Dict[str, Any]] = []
        agent_route = route_result
        if self._requires_incident_knowledge(route_result):
            knowledge_route = {**route_result, "target_agent": "memory_ops"}
            knowledge_result = await self._execute_agent(knowledge_route)
            knowledge_failed = self._agent_failed(knowledge_result)
            agent_trace.append(
                self._agent_trace_step(
                    "memory_ops",
                    knowledge_route,
                    "FAILED" if knowledge_failed else "SUCCEEDED",
                )
            )
            references = self._knowledge_references(knowledge_result)
            experience_references = self._experience_references(references)
            if not knowledge_failed and experience_references:
                persona_route = self._experience_persona_route(route_result, references)
                experience_persona_result = await self._execute_agent(persona_route)
                persona_failed = self._agent_failed(experience_persona_result)
                agent_trace.append(
                    self._agent_trace_step(
                        "persona",
                        persona_route,
                        "FAILED" if persona_failed else "SUCCEEDED",
                    )
                )
                if persona_failed:
                    return self._failed_agent_result(
                        route_result=route_result,
                        agent_result=experience_persona_result,
                        knowledge_result=knowledge_result,
                        trace_id=trace_id,
                        agent_trace=agent_trace,
                    )

            knowledge_context = self._commander_knowledge_context(
                knowledge_result,
                references,
            )
            if experience_persona_result is not None:
                knowledge_context = (
                    f"{knowledge_context}\n"
                    f"Persona 对已授权经验的受约束表达："
                    f"{self._agent_reply(experience_persona_result) or ''}"
                )
            agent_route = {
                **route_result,
                "knowledge_context": knowledge_context,
                "knowledge_references": references,
                "knowledge_available": not knowledge_failed,
            }

        agent_result = await self._execute_agent(agent_route)
        agent_failed = self._agent_failed(agent_result)
        agent_trace.append(
            self._agent_trace_step(
                route_result.get("target_agent", "unknown"),
                route_result,
                "FAILED" if agent_failed else "SUCCEEDED",
            )
        )
        if route_result.get("target_agent") == "memory_ops":
            knowledge_result = agent_result
            references = self._knowledge_references(knowledge_result)
            experience_references = self._experience_references(references)

        if agent_failed:
            return self._failed_agent_result(
                route_result=route_result,
                agent_result=agent_result,
                knowledge_result=knowledge_result,
                trace_id=trace_id,
                agent_trace=agent_trace,
            )

        if route_result.get("target_agent") == "memory_ops" and experience_references:
            persona_route = self._experience_persona_route(route_result, references)
            experience_persona_result = await self._execute_agent(persona_route)
            persona_failed = self._agent_failed(experience_persona_result)
            agent_trace.append(
                self._agent_trace_step(
                    "persona",
                    persona_route,
                    "FAILED" if persona_failed else "SUCCEEDED",
                )
            )
            if persona_failed:
                return self._failed_agent_result(
                    route_result=route_result,
                    agent_result=experience_persona_result,
                    knowledge_result=knowledge_result,
                    trace_id=trace_id,
                    agent_trace=agent_trace,
                )
            agent_result = experience_persona_result

        if experience_persona_result is not None and experience_references:
            try:
                await ExperienceUsageLedger(self.container.db_client).record_references(
                    ExperienceUsageContext(
                        venue_id=str(route_result.get("venue_id") or ""),
                        user_id=str(route_result.get("from_user") or ""),
                        message_id=str(route_result.get("msg_id") or ""),
                        trace_id=str(trace_id or ""),
                        session_id=str(route_result.get("session_id") or ""),
                        retrieval_snapshot_id=str(
                            self._structured_data(knowledge_result).get(
                                "retrieval_snapshot_id"
                            )
                            or ""
                        ),
                        query_text=str(route_result.get("content") or ""),
                    ),
                    experience_references,
                )
            except (ExperienceUsagePersistenceError, ValueError) as exc:
                logger.error(
                    f"[Trace-{trace_id}] 专家经验采用记录失败 "
                    f"[error_type={type(exc).__name__}]"
                )
                return {
                    "status": "failed",
                    "route": route_result,
                    "agent_result": agent_result,
                    "knowledge_result": knowledge_result,
                    "reply_text": "专家经验引用暂时无法完成审计，请由值班经理人工核验。",
                    "error": "Experience usage persistence failed",
                    "trace_id": trace_id,
                    "agent_trace": agent_trace,
                }

        try:
            event_id = await self._save_live_event(payload, route_result)
            event_record = (
                await self.container.db_client.fetch_one(
                    "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
                    (event_id, route_result.get("venue_id", "")),
                )
                if event_id
                else None
            )
        except Exception as exc:
            logger.error(f"[Trace-{trace_id}] 实时事件持久化失败: {exc}")
            return {
                "status": "failed",
                "route": route_result,
                "agent_result": agent_result,
                "knowledge_result": knowledge_result,
                "reply_text": self._agent_reply(agent_result),
                "error": f"Live event persistence failed: {exc}",
                "trace_id": trace_id,
                "agent_trace": agent_trace,
            }

        business_cards = self._build_business_cards(
            event_id=event_id,
            event_record=event_record,
            route_result=route_result,
            knowledge_result=knowledge_result,
            agent_result=agent_result,
        )

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
            "knowledge_result": knowledge_result,
            "reply_text": self._agent_reply(agent_result),
            "trace_id": trace_id,
            "agent_trace": agent_trace,
            "event_id": event_id,
            "business_cards": business_cards,
        }

    async def _save_message(self, payload: Dict[str, Any]):
        """保存消息到数据库"""
        db_client = self.container.db_client
        msg_id = payload.get("msg_id", "")
        session_id = payload.get("session_id") or msg_id
        from_user = payload.get("from_user", "unknown")
        venue_id = payload.get("venue_id", "")
        now = time.time()

        session_row_count = await db_client.execute(
            """
            INSERT INTO sessions (
                session_id, user_id, venue_id, agent_name, stage, message_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'router', 'active', 1, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                message_count = sessions.message_count + 1,
                updated_at = excluded.updated_at
            WHERE sessions.venue_id = excluded.venue_id
              AND sessions.user_id = excluded.user_id
            """,
            (session_id, from_user, venue_id, now, now),
        )
        if session_row_count != 1:
            raise ValueError("会话不属于当前场地")

        await db_client.execute(
            """
            INSERT INTO messages (
                message_id, session_id, from_user, msg_type, content, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO NOTHING
            """,
            (
                msg_id,
                session_id,
                from_user,
                payload.get("msg_type", "text"),
                payload.get("content", ""),
                now,
                json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
            ),
        )

    async def _route(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        路由决策

        集成 ContextTrigger 两阶段过滤：
        1. 先调用 ContextTrigger 进行 Stage1 关键词预过滤
        2. 根据结果决定：
           - 被排除 → 跳过处理
           - 应触发 → 将事件上下文交给 Router 分诊
           - 其他 → 继续 Router 正常路由

        Args:
            payload: 消息载荷

        Returns:
            路由结果
        """
        msg_id = payload.get("msg_id", "unknown")
        trace_id = payload.get("trace_id", "")
        raw_text = payload.get("content", "")
        venue_id = payload.get("venue_id", "")
        session_id = payload.get("session_id") or msg_id
        agent_trace = []
        context_trigger_data = None

        try:
            # ================================================================
            # Demo: demo_todo_decompose msg_type bypass
            # 必须在 ContextTrigger 之前，防止被拦截路由到 Commander
            # ================================================================
            if payload.get("msg_type") == "demo_todo_decompose":
                return {
                    "status": "routed",
                    "target_agent": "todo_write",
                    "content": raw_text,
                    "from_user": payload.get("from_user", "unknown"),
                    "trace_id": trace_id,
                    "venue_id": venue_id,
                    "session_id": session_id,
                    "priority": "P3",
                    "intent": "task_decomposition",
                    "agent_trace": agent_trace,
                }

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
                        "msg_id": msg_id,
                        "venue_id": venue_id,
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "_database": self.container.db_client,
                    }
                    ct_result = await context_trigger.run(ct_context, trace_id=trace_id)
                    agent_trace.append(
                        self._agent_trace_step(
                            "context_trigger",
                            {
                                "trace_id": trace_id,
                                "venue_id": venue_id,
                                "session_id": session_id,
                            },
                            "SUCCEEDED" if ct_result.success else "FAILED",
                        )
                    )

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
                                "venue_id": venue_id,
                                "session_id": session_id,
                                "agent_trace": agent_trace,
                            }

                        # Stage2 结果作为 Router 的分诊上下文，不绕过 Router。
                        if sd.get("should_trigger"):
                            severity = sd.get("severity", "P2")
                            event_type = sd.get("event_type", "其他")
                            logger.info(
                                f"[Trace-{trace_id}] ContextTrigger 触发处置: "
                                f"severity={severity}, event_type={event_type}"
                            )
                            context_trigger_data = {
                                "stage": stage,
                                "should_trigger": True,
                                "event_type": event_type,
                                "severity": severity,
                                "confidence": sd.get("confidence", 0.0),
                                "reason": (sd.get("stage2_result") or {}).get("reason", ""),
                                "stage1_keywords": sd.get("stage1_result", {}).get("hit_keywords", []),
                            }

                except Exception as e:
                    logger.warning(f"[Trace-{trace_id}] ContextTrigger 执行异常，降级到 Router: {e}")
                    agent_trace.append(
                        self._agent_trace_step(
                            "context_trigger",
                            {
                                "trace_id": trace_id,
                                "venue_id": venue_id,
                                "session_id": session_id,
                            },
                            "FAILED",
                        )
                    )
                    # ContextTrigger 异常时，继续走 Router

            # ================================================================
            # 阶段 1: Router 正常路由
            # ================================================================
            router = get_skill_by_name("router")
            if not router:
                logger.warning("⚠️ Router 技能未注册")
                return None

            # 传入 raw_text（Router._validate_context 要求此字段）
            context = {
                "raw_text": raw_text,
                "msg_id": msg_id,
                "from_user": payload.get("from_user", "unknown"),
                "venue_id": venue_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "context_trigger_data": context_trigger_data,
            }
            result = await router.run(context, trace_id=trace_id)
            agent_trace.append(
                self._agent_trace_step(
                    "router",
                    {
                        "trace_id": trace_id,
                        "venue_id": venue_id,
                        "session_id": session_id,
                    },
                    "SUCCEEDED" if result.success else "FAILED",
                )
            )

            if hasattr(result, "success") and not result.success:
                return {
                    "status": "failed",
                    "target_agent": "router",
                    "error": getattr(result, "error_msg", None) or "Router execution failed",
                    "reply_text": getattr(result, "reply_text", None),
                    "trace_id": trace_id,
                    "venue_id": venue_id,
                    "session_id": session_id,
                    "agent_trace": agent_trace,
                }

            # Router 返回的是 SkillOutput，需要提取 structured_data
            if hasattr(result, 'structured_data'):
                sd = result.structured_data
                intent = str(sd.get("intent") or "other").strip().lower()
                target_agent = self._intent_to_agent(intent)
                router_severity = sd.get("severity", "P3")
                trigger_severity = (context_trigger_data or {}).get("severity")
                severity = self._highest_severity(router_severity, trigger_severity)
                metadata = payload.get("metadata") or {}
                attachments = metadata.get("attachments") or []
                return {
                    "status": "routed" if target_agent else "responded",
                    "intent": intent,
                    "severity": severity,
                    "priority": severity,
                    "target_agent": target_agent,
                    "reply_text": (
                        None
                        if target_agent
                        else self._general_assistant_reply(intent)
                    ),
                    "from_user": payload.get("from_user", "unknown"),
                    "content": raw_text,
                    "summary": sd.get("summary", ""),
                    "event_type": (context_trigger_data or {}).get("event_type", ""),
                    "risk_reason": (context_trigger_data or {}).get("reason", ""),
                    "attachments": attachments if isinstance(attachments, list) else [],
                    "attachment_context": self._attachment_context(attachments),
                    "timestamp": payload.get("timestamp", time.time()),
                    "msg_id": msg_id,
                    "trace_id": trace_id,
                    "venue_id": venue_id,
                    "session_id": session_id,
                    "context_trigger_data": context_trigger_data,
                    "agent_trace": agent_trace,
                    "router_confidence": sd.get("confidence", 0.0),
                }

            return result

        except Exception as e:
            logger.error(f"❌ 路由失败: {e}")
            return None

    def _intent_to_agent(self, intent: str) -> Optional[str]:
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
            "other": "memory_ops",               # 日常咨询 → 确权知识检索
        }
        return intent_agent_map.get(intent)

    @staticmethod
    def _general_assistant_reply(intent: str) -> str:
        if intent == "chitchat":
            return (
                "你好，我是企业运营助手。你可以直接上报现场事件、查询已发布知识与"
                "授权经验、处理分配给你的任务，或提交处置结果。"
            )
        return (
            "我暂时无法确认你要办理的业务。请补充现场情况，或明确选择上报事件、"
            "查询经验、查看任务、提交结果中的一项。"
        )

    @staticmethod
    def _highest_severity(*values: Optional[str]) -> str:
        severity_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
        normalized = [str(value).upper() for value in values if str(value or "").upper() in severity_rank]
        if not normalized:
            return "P3"
        return min(normalized, key=severity_rank.__getitem__)

    @staticmethod
    def _attachment_context(attachments: Any) -> str:
        if not isinstance(attachments, list) or not attachments:
            return "未提供附件说明"
        summaries = []
        for attachment in attachments[:20]:
            if not isinstance(attachment, dict):
                continue
            details = [
                str(attachment.get("name") or "附件").strip(),
                str(attachment.get("type") or attachment.get("content_type") or "").strip(),
                str(attachment.get("description") or attachment.get("note") or "").strip(),
                str(attachment.get("external_ref") or attachment.get("url") or "").strip(),
            ]
            readable = "；".join(detail for detail in details if detail)
            if readable:
                summaries.append(readable)
        return "\n".join(f"- {summary}" for summary in summaries) or "未提供附件说明"

    @staticmethod
    def _requires_incident_knowledge(route_result: Dict[str, Any]) -> bool:
        return (
            route_result.get("target_agent") == "commander"
            and route_result.get("intent") in {"incident_report", "emergency_dispatch"}
        )

    @staticmethod
    def _agent_failed(result: Any) -> bool:
        if result is None:
            return True
        if hasattr(result, "success"):
            return not bool(result.success)
        if isinstance(result, dict):
            return str(result.get("status", "")).lower() in {"failed", "skipped"}
        return True

    @staticmethod
    def _agent_reply(result: Any) -> Optional[str]:
        if result is None:
            return None
        if hasattr(result, "reply_text"):
            return result.reply_text
        if isinstance(result, dict):
            return result.get("reply_text")
        return None

    @staticmethod
    def _agent_error(result: Any) -> str:
        if result is None:
            return "Agent execution failed"
        if hasattr(result, "error_msg"):
            return result.error_msg or "Agent execution failed"
        if isinstance(result, dict):
            return result.get("error") or result.get("reason") or "Agent execution failed"
        return "Agent execution failed"

    @staticmethod
    def _structured_data(result: Any) -> Dict[str, Any]:
        if result is None:
            return {}
        if hasattr(result, "structured_data") and isinstance(result.structured_data, dict):
            return result.structured_data
        if isinstance(result, dict) and isinstance(result.get("structured_data"), dict):
            return result["structured_data"]
        return {}

    @classmethod
    def _knowledge_references(cls, knowledge_result: Any) -> list[Dict[str, Any]]:
        references = cls._structured_data(knowledge_result).get("references") or []
        if not isinstance(references, list):
            return []
        verified = []
        required_fields = {"source_id", "source_type", "source_label", "title", "version", "status"}
        for reference in references:
            if not isinstance(reference, dict) or not required_fields.issubset(reference):
                continue
            if any(reference.get(field) in {None, ""} for field in required_fields):
                continue
            verified.append(dict(reference))
        return verified

    @staticmethod
    def _experience_references(
        references: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        return [
            reference
            for reference in references
            if str(reference.get("source_type") or "").upper()
            in {"EXPERIENCE", "EXPERIENCE_CARD"}
        ]

    @staticmethod
    def _experience_persona_route(
        route_result: Dict[str, Any],
        references: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            **route_result,
            "target_agent": "persona",
            "knowledge_references": references,
            "knowledge_available": True,
            "persona_trigger": "AUTHORIZED_RETRIEVAL",
        }

    @classmethod
    def _failed_agent_result(
        cls,
        *,
        route_result: Dict[str, Any],
        agent_result: Any,
        knowledge_result: Any,
        trace_id: str,
        agent_trace: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        error = cls._agent_error(agent_result)
        logger.error(
            f"[Trace-{trace_id}] Agent 执行失败 "
            f"[Agent={route_result.get('target_agent')}] [error={error}]"
        )
        return {
            "status": "failed",
            "route": route_result,
            "agent_result": agent_result,
            "knowledge_result": knowledge_result,
            "reply_text": cls._agent_reply(agent_result),
            "error": error,
            "trace_id": trace_id,
            "agent_trace": agent_trace,
        }

    @classmethod
    def _commander_knowledge_context(
        cls,
        knowledge_result: Any,
        references: list[Dict[str, Any]],
    ) -> str:
        if cls._agent_failed(knowledge_result):
            return "知识检索当前不可用。不得构造或暗示任何 SOP、案例或专家经验引用。"
        if not references:
            return "未找到已发布依据。不得构造或暗示任何 SOP、案例或专家经验引用。"

        advice = cls._agent_reply(knowledge_result) or ""
        reference_snapshot = json.dumps(references, ensure_ascii=False, default=str)
        lines = [
            f"MemoryOps 检索建议：{advice}",
            f"允许引用的来源快照：{reference_snapshot}",
        ]
        if not any(
            reference.get("source_type") in {"HISTORY", "CASE", "EXPERIENCE", "EXPERIENCE_CARD"}
            for reference in references
        ):
            lines.append("尚未找到与本次根因完全一致的历史经验。")
        return "\n".join(lines)

    @staticmethod
    def _event_business_code(event_id: str, timestamp: Any) -> str:
        return build_business_id("SJ", event_id, timestamp)

    @staticmethod
    def _severity_label(severity: str) -> str:
        labels = {
            "P0": "P0 / 极高生命安全风险",
            "P1": "P1 / 重大设备安全风险",
            "P2": "P2 / 一般运营风险",
            "P3": "P3 / 低风险现场事项",
            "P4": "P4 / 日常咨询事项",
        }
        return labels.get(str(severity).upper(), "风险等级待确认")

    @classmethod
    def _build_business_cards(
        cls,
        *,
        event_id: Optional[str],
        event_record: Optional[Dict[str, Any]],
        route_result: Dict[str, Any],
        knowledge_result: Any,
        agent_result: Any,
    ) -> list[Dict[str, Any]]:
        cards: list[Dict[str, Any]] = []
        commander_data = cls._structured_data(agent_result)
        severity = str(route_result.get("severity") or "P3").upper()
        event_type = str(route_result.get("event_type") or "现场事件").strip()
        title = str(route_result.get("summary") or f"{event_type}处置").strip()
        risk_reason = str(
            commander_data.get("risk_reason")
            or route_result.get("risk_reason")
            or "系统已根据现场信息完成风险判断"
        ).strip()
        next_step = str(commander_data.get("next_step_check") or "请继续补充现场检查结果").strip()

        if event_id:
            cards.append(
                {
                    "card_type": "event",
                    "resource_id": event_id,
                    "business_code": (
                        (event_record or {}).get("business_id")
                        or cls._event_business_code(event_id, route_result.get("timestamp"))
                    ),
                    "title": title,
                    "summary": risk_reason,
                    "severity": severity,
                    "severity_label": cls._severity_label(severity),
                    "status": "OPEN",
                    "owner_name": "值班经理待分派",
                    "next_action": next_step,
                    "employee_url": f"/assistant/work/event/{event_id}",
                }
            )

        reply_text = cls._agent_reply(agent_result)
        if reply_text:
            cards.append(
                {
                    "card_type": "disposition",
                    "title": f"{cls._severity_label(severity)}处置建议",
                    "summary": reply_text,
                    "recommended_action": next_step,
                    "risk_reason": risk_reason,
                    "required_tools": commander_data.get("required_tools") or [],
                    "immediate_actions": commander_data.get("immediate_actions") or [],
                }
            )

        references = cls._knowledge_references(knowledge_result)
        for reference in references:
            source_type = reference["source_type"]
            card_type = {
                "SOP": "sop_reference",
                "HISTORY": "case_reference",
                "CASE": "case_reference",
                "EXPERIENCE": "experience_reference",
                "EXPERIENCE_CARD": "experience_reference",
            }.get(source_type, "knowledge_reference")
            reference_card = {
                "card_type": card_type,
                "resource_id": reference["source_id"],
                "business_code": reference.get("business_id") or "",
                "vector_doc_id": reference.get("vector_doc_id") or "",
                "source_id": reference["source_id"],
                "source_type": source_type,
                "source_name": reference["source_label"],
                "source_title": reference["title"],
                "title": reference["title"],
                "summary": reference.get("content") or "",
                "version": reference["version"],
                "version_label": f"v{reference['version']}",
                "status": reference["status"],
                "expert_name": reference.get("expert_name") or "",
                "publisher_name": reference.get("publisher_name") or "",
                "published_at": reference.get("published_at"),
                "relevance": reference.get("score"),
                "source_event_business_id": (
                    reference.get("source_event_business_id") or ""
                ),
                "applicable_context": reference.get("applicable_context") or "",
                "authorization_scopes": reference.get("authorization_scopes") or [],
            }
            if source_type == "SOP":
                encoded_version = quote(str(reference["version"]), safe="")
                reference_card["employee_url"] = (
                    f"/assistant/knowledge/sop/{reference['source_id']}?version={encoded_version}"
                )
            cards.append(reference_card)

        if knowledge_result is not None and not any(
            reference["source_type"] in {"HISTORY", "CASE", "EXPERIENCE", "EXPERIENCE_CARD"}
            for reference in references
        ):
            summary = (
                "知识检索当前不可用，系统未生成任何虚假引用。请联系值班经理人工核验依据。"
                if cls._agent_failed(knowledge_result)
                else (
                    "已匹配正式 SOP；尚未找到与本次根因完全一致的历史经验。"
                    if references
                    else "尚未找到已发布依据，系统未生成任何虚假引用。"
                )
            )
            cards.append(
                {
                    "card_type": "knowledge_notice",
                    "title": "知识检索说明",
                    "summary": summary,
                }
            )

        return cards

    @staticmethod
    def _agent_trace_step(agent_name: str, context: Dict[str, Any], status: str) -> Dict[str, Any]:
        agent_ids = {
            "context_trigger": "ContextTrigger",
            "router": "Router",
            "commander": "Commander",
            "memory_ops": "MemoryOps",
            "persona": "Persona",
            "persona_extract": "PersonaExtract",
            "todo_write": "TodoWrite",
            "watcher": "Watcher",
        }
        return {
            "agent_id": agent_ids.get(agent_name, agent_name),
            "agent_name": agent_name,
            "status": status,
            "trace_id": context.get("trace_id", ""),
            "venue_id": context.get("venue_id", ""),
            "session_id": context.get("session_id", ""),
        }

    async def _save_live_event(
        self,
        payload: Dict[str, Any],
        route_result: Dict[str, Any],
    ) -> Optional[str]:
        venue_id = route_result.get("venue_id") or payload.get("venue_id", "")
        if not venue_id or route_result.get("target_agent") not in {"commander", "memory_ops"}:
            return None

        intent = route_result.get("intent", "")
        if intent not in {"incident_report", "emergency_dispatch", "emergency_advice"}:
            return None

        message_id = payload.get("msg_id", "")
        existing = await self.container.db_client.fetch_one(
            """
            SELECT event_id FROM confirmed_events
            WHERE push_id = ? AND venue_id = ? AND source_type = 'LIVE'
            """,
            (message_id, venue_id),
        )
        if existing:
            return existing["event_id"]

        metadata = payload.get("metadata") or {}
        source_event_id = str(
            metadata.get("source_event_id") or metadata.get("event_id") or ""
        ).strip()
        if source_event_id:
            source_event = await self.container.db_client.fetch_one(
                """
                SELECT * FROM confirmed_events
                WHERE event_id = ? AND venue_id = ? AND source_type = 'LIVE'
                """,
                (source_event_id, venue_id),
            )
            if source_event is None:
                raise ValueError("关联事件不存在或不属于当前场地")

            session_id = str(payload.get("session_id") or "").strip()
            session_link = await self.container.db_client.fetch_one(
                """
                SELECT activity.id
                FROM event_activities AS activity
                JOIN sessions AS session
                  ON session.session_id = activity.session_id
                 AND session.venue_id = activity.venue_id
                WHERE activity.venue_id = ? AND activity.event_id = ?
                  AND activity.session_id = ? AND session.user_id = ?
                LIMIT 1
                """,
                (
                    venue_id,
                    source_event_id,
                    session_id,
                    str(payload.get("from_user") or ""),
                ),
            )
            if session_link is None:
                raise ValueError("关联事件不属于当前会话")
            return await self._update_live_event(
                source_event,
                payload=payload,
                route_result=route_result,
            )

        context_trigger_data = route_result.get("context_trigger_data") or {}
        from src.memory_palace.knowledge.db_client import save_confirmed_event

        return await save_confirmed_event(
            push_id=message_id,
            from_user=payload.get("from_user", "unknown"),
            raw_text=payload.get("content", ""),
            event_type=context_trigger_data.get("event_type", "其他"),
            severity=route_result.get("severity") or context_trigger_data.get("severity", "P3"),
            context_trigger_data=context_trigger_data,
            source_type="LIVE",
            venue_id=venue_id,
            trace_id=route_result.get("trace_id") or payload.get("trace_id", ""),
            database=self.container.db_client,
            vector_client=self.container.vector_store,
        )

    @staticmethod
    def _decode_json_object(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _live_event_vector_metadata(event: Dict[str, Any], severity: str) -> Dict[str, Any]:
        event_id = str(event["event_id"])
        return {
            "event_type": str(event.get("event_type") or "其他"),
            "severity": severity,
            "from_user": str(event.get("from_user") or "unknown"),
            "event_id": event_id,
            "business_id": str(event.get("business_id") or ""),
            "venue_id": str(event.get("venue_id") or ""),
            "title": f"{event.get('event_type') or '其他'}事件",
            "source_type": "LIVE",
            "source_id": event_id,
            "version": 1,
            "status": str(event.get("status") or "OPEN"),
        }

    async def _update_live_event(
        self,
        event: Dict[str, Any],
        *,
        payload: Dict[str, Any],
        route_result: Dict[str, Any],
    ) -> str:
        database = self.container.db_client
        event_id = str(event["event_id"])
        venue_id = str(event.get("venue_id") or "")
        message_id = str(payload.get("msg_id") or "")
        trace_id = str(route_result.get("trace_id") or payload.get("trace_id") or "")
        session_id = str(payload.get("session_id") or "")
        content = str(payload.get("content") or "").strip()
        activity_key = f"event-updated:{message_id}"

        existing_activity = await database.fetch_one(
            """
            SELECT id FROM event_activities
            WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
            """,
            (venue_id, event_id, activity_key),
        )
        if existing_activity:
            return event_id

        if event.get("status") != "OPEN":
            raise ValueError("已闭环事件不能继续补充")

        original_context = self._decode_json_object(event.get("context_trigger_data"))
        supplements = original_context.get("supplements")
        if not isinstance(supplements, list):
            supplements = []
        supplement_already_applied = any(
            isinstance(item, dict) and str(item.get("message_id") or "") == message_id
            for item in supplements
        )

        metadata = payload.get("metadata") or {}
        confirmed_location = str(metadata.get("confirmed_location") or "").strip()[:200]
        attachments = metadata.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        now = time.time()
        supplement = {
            "message_id": message_id,
            "trace_id": trace_id,
            "session_id": session_id,
            "content": content,
            "confirmed_location": confirmed_location,
            "attachments": attachments,
            "created_at": now,
        }
        original_raw_text = str(event.get("raw_text") or "").strip()
        event_type = str(event.get("event_type") or "其他")
        original_memory = str(event.get("memory_content") or "")
        original_severity = str(event.get("severity") or "P3")
        original_updated_at = event.get("updated_at")
        vector_doc_id = str(event.get("vector_doc_id") or "")
        vector_store = self.container.vector_store
        event_mutated = False
        audit_created = False

        if supplement_already_applied:
            updated_context = original_context
            updated_raw_text = original_raw_text
            severity = original_severity
            updated_memory = original_memory or f"[{severity}] {event_type}事件：{updated_raw_text}"
        else:
            updated_context = {
                **original_context,
                "supplements": [*supplements, supplement],
                "latest_trace_id": trace_id,
            }
            if confirmed_location:
                updated_context["confirmed_location"] = confirmed_location
            updated_raw_text = "\n\n".join(
                part for part in (original_raw_text, f"补充信息：{content}") if part
            )
            severity = self._highest_severity(
                original_severity,
                str(route_result.get("severity") or "P3"),
            )
            updated_memory = f"[{severity}] {event_type}事件：{updated_raw_text}"
            updated = await database.execute(
                """
                UPDATE confirmed_events
                SET raw_text = ?, severity = ?, context_trigger_data = ?,
                    memory_content = ?, updated_at = ?
                WHERE event_id = ? AND venue_id = ? AND status = 'OPEN'
                  AND COALESCE(updated_at, -1) = COALESCE(?, -1)
                """,
                (
                    updated_raw_text,
                    severity,
                    json.dumps(updated_context, ensure_ascii=False, sort_keys=True),
                    updated_memory,
                    now,
                    event_id,
                    venue_id,
                    original_updated_at,
                ),
            )
            if updated != 1:
                raise ValueError("事件状态已变化，不能继续补充")
            event_mutated = True

        try:
            if vector_store is None or not vector_doc_id:
                raise RuntimeError("向量库未初始化，不能更新事件记忆")
            stored = vector_store.upsert_experience(
                updated_memory,
                self._live_event_vector_metadata({**event, "severity": severity}, severity),
                vector_doc_id,
                strict=True,
            )
            if stored is False:
                raise RuntimeError("向量库拒绝更新事件记忆")

            existing_audit = await database.fetch_one(
                """
                SELECT id FROM audit_logs
                WHERE venue_id = ? AND action = 'EVENT_UPDATED'
                  AND resource_type = 'event' AND resource_id = ? AND trace_id = ?
                LIMIT 1
                """,
                (venue_id, event_id, trace_id),
            )
            if existing_audit is None:
                await database.execute(
                    """
                    INSERT INTO audit_logs (
                        venue_id, user_id, action, resource_type, resource_id,
                        outcome, trace_id, metadata_json, created_at
                    ) VALUES (?, ?, 'EVENT_UPDATED', 'event', ?,
                              'SUCCEEDED', ?, ?, ?)
                    """,
                    (
                        venue_id,
                        str(payload.get("from_user") or ""),
                        event_id,
                        trace_id,
                        json.dumps(
                            {
                                "message_id": message_id,
                                "session_id": session_id,
                                "confirmed_location": confirmed_location,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                audit_created = True

            await append_event_activity(
                database,
                venue_id=venue_id,
                event_id=event_id,
                activity_type="EVENT_UPDATED",
                created_by=str(payload.get("from_user") or ""),
                session_id=session_id,
                message_id=message_id,
                trace_id=trace_id,
                payload={
                    "business_id": event.get("business_id"),
                    "summary": content,
                    "confirmed_location": confirmed_location,
                    "attachments": attachments,
                },
                idempotency_key=activity_key,
                created_at=now,
            )
        except Exception as update_error:
            compensation_errors = []
            try:
                await database.execute(
                    """
                    DELETE FROM event_activities
                    WHERE venue_id = ? AND event_id = ? AND idempotency_key = ?
                    """,
                    (venue_id, event_id, activity_key),
                )
            except Exception as cleanup_error:
                compensation_errors.append(f"activity_cleanup={cleanup_error}")
            if audit_created:
                try:
                    await database.execute(
                        """
                        DELETE FROM audit_logs
                        WHERE venue_id = ? AND action = 'EVENT_UPDATED'
                          AND resource_type = 'event' AND resource_id = ? AND trace_id = ?
                        """,
                        (venue_id, event_id, trace_id),
                    )
                except Exception as cleanup_error:
                    compensation_errors.append(f"audit_cleanup={cleanup_error}")
            if event_mutated:
                try:
                    await database.execute(
                        """
                        UPDATE confirmed_events
                        SET raw_text = ?, severity = ?, context_trigger_data = ?,
                            memory_content = ?, updated_at = ?
                        WHERE event_id = ? AND venue_id = ? AND updated_at = ?
                        """,
                        (
                            original_raw_text,
                            original_severity,
                            json.dumps(original_context, ensure_ascii=False, sort_keys=True),
                            original_memory,
                            original_updated_at,
                            event_id,
                            venue_id,
                            now,
                        ),
                    )
                except Exception as cleanup_error:
                    compensation_errors.append(f"event_restore={cleanup_error}")
            try:
                current_event = await database.fetch_one(
                    "SELECT * FROM confirmed_events WHERE event_id = ? AND venue_id = ?",
                    (event_id, venue_id),
                )
                if current_event and vector_store is not None and vector_doc_id:
                    current_severity = str(current_event.get("severity") or "P3")
                    current_memory = str(current_event.get("memory_content") or "")
                    vector_store.upsert_experience(
                        current_memory,
                        self._live_event_vector_metadata(current_event, current_severity),
                        vector_doc_id,
                        strict=True,
                    )
            except Exception as cleanup_error:
                compensation_errors.append(f"vector_realign={cleanup_error}")
            if compensation_errors:
                logger.error(
                    f"[Trace-{trace_id}] 事件续报补偿不完整: "
                    + "; ".join(compensation_errors)
                )
            raise update_error

        return event_id

    async def _default_route(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        默认路由

        Args:
            payload: 消息载荷

        Returns:
            默认路由结果
        """
        return {
            "status": "failed",
            "intent": "unclassified",
            "priority": payload.get("priority", "P3"),
            "target_agent": "router",
            "reply_text": "暂时未能判断这条消息需要办理的业务，请稍后重试或联系值班经理。",
            "error": "ROUTING_UNAVAILABLE",
            "from_user": payload.get("from_user", "unknown"),
            "content": payload.get("content", ""),
            "msg_id": payload.get("msg_id", ""),
            "trace_id": payload.get("trace_id", ""),
            "venue_id": payload.get("venue_id", ""),
            "session_id": payload.get("session_id") or payload.get("msg_id", ""),
            "agent_trace": [],
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
                context.update(
                    {
                        "raw_text": route_result.get("content", ""),
                        "msg_id": route_result.get("msg_id", ""),
                        "trace_id": trace_id,
                        "venue_id": route_result.get("venue_id", ""),
                        "session_id": session_id,
                        "context_trigger_data": route_result.get("context_trigger_data"),
                        "summary": route_result.get("summary", ""),
                        "event_type": route_result.get("event_type", ""),
                        "risk_reason": route_result.get("risk_reason", ""),
                        "attachments": route_result.get("attachments") or [],
                        "attachment_context": route_result.get("attachment_context", ""),
                        "knowledge_context": route_result.get("knowledge_context", ""),
                        "knowledge_references": route_result.get("knowledge_references") or [],
                        "knowledge_available": route_result.get("knowledge_available"),
                        "persona_trigger": route_result.get("persona_trigger"),
                        "_database": self.container.db_client,
                    }
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
                    "venue_id": route_result.get("venue_id", ""),
                    "session_id": session_id,
                    "context_trigger_data": route_result.get("context_trigger_data"),
                    "summary": route_result.get("summary", ""),
                    "event_type": route_result.get("event_type", ""),
                    "risk_reason": route_result.get("risk_reason", ""),
                    "attachments": route_result.get("attachments") or [],
                    "attachment_context": route_result.get("attachment_context", ""),
                    "knowledge_context": route_result.get("knowledge_context", ""),
                    "knowledge_references": route_result.get("knowledge_references") or [],
                    "knowledge_available": route_result.get("knowledge_available"),
                    "persona_trigger": route_result.get("persona_trigger"),
                    "_database": self.container.db_client,
                }

            if target_agent == "memory_ops":
                context["_knowledge_retriever"] = self.container.knowledge_retriever

            # 执行技能
            result = await skill.run(context, trace_id=trace_id)

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
            await self.container.db_client.execute(
                "UPDATE messages SET sla_response_at = ? WHERE message_id = ?",
                (time.time(), msg_id),
            )
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

