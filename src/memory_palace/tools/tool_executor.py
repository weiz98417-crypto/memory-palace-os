"""
工具执行器 (Tool Executor)

核心职责:
1. 统一管理所有工具的注册和执行
2. 集成权限引擎，所有工具调用都经过权限检查
3. 提供工具执行结果标准化

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import inspect
import json
from typing import Any, Callable, Dict, Optional, cast

from loguru import logger

# 工具注册表
_tools: Dict[str, Callable] = {}
_tools_metadata: Dict[str, Dict[str, Any]] = {}


def register_tool(
    name: str,
    func: Callable,
    description: str = "",
    parameters: Optional[Dict[str, Any]] = None
):
    """
    注册工具

    Args:
        name: 工具名称
        func: 工具函数 (可以是 async 或 sync)
        description: 工具描述
        parameters: OpenAI tool format 参数定义
    """
    _tools[name] = func
    _tools_metadata[name] = {
        "name": name,
        "description": description,
        "parameters": parameters or {}
    }
    logger.debug(f"[ToolExecutor] 注册工具: {name}")


def get_tool(name: str) -> Optional[Callable]:
    """获取工具函数"""
    return _tools.get(name)


def list_tools() -> Dict[str, Dict[str, Any]]:
    """列出所有已注册工具"""
    return _tools_metadata.copy()


async def execute_tool(
    name: str,
    args: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    执行已注册的工具

    Args:
        name: 工具名称
        args: 工具参数

    Returns:
        {"status": "executed", "result": ...} 或 {"status": "error", "message": ...}
    """
    if name not in _tools:
        return {
            "status": "error",
            "message": f"Tool '{name}' not found. Available tools: {list(_tools.keys())}"
        }

    try:
        func = _tools[name]
        call_args = dict(args)
        if context is not None and "execution_context" in inspect.signature(func).parameters:
            call_args["execution_context"] = context

        # 判断是 async 还是 sync 函数
        if asyncio.iscoroutinefunction(func):
            result = await func(**call_args)
        else:
            result = func(**call_args)

        return {
            "status": "executed",
            "result": result
        }

    except TypeError as e:
        # 参数错误
        logger.error(f"[ToolExecutor] 工具 {name} 参数错误: {e}")
        return {
            "status": "error",
            "message": f"Invalid arguments for tool '{name}': {e}"
        }
    except Exception as e:
        logger.error(f"[ToolExecutor] 工具 {name} 执行失败: {e}")
        return {
            "status": "error",
            "code": getattr(e, "code", "TOOL_EXECUTION_FAILED"),
            "message": str(e),
        }


async def execute_with_permission(
    tool_name: str,
    args: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    通过权限引擎执行工具

    这是推荐的工具调用方式。

    Args:
        tool_name: 工具名称
        args: 工具参数
        context: 执行上下文

    Returns:
        {
            "status": "executed", "result": ...          # 执行成功
            "status": "pending_approval", "approval_id": ... # 等待审批
            "status": "cooldown", "retry_after": ...     # 冷却中
            "status": "error", "message": ...            # 错误
        }
    """
    from ..core.permissions import get_permission_engine

    engine = get_permission_engine()
    return cast(
        Dict[str, Any],
        await engine.check_and_execute(tool_name, args, context),
    )


def get_openai_tools_format() -> list:
    """
    获取 OpenAI tools API 格式的工具定义

    Returns:
        OpenAI compatible tools list
    """
    tools: list[dict[str, Any]] = []
    for name, metadata in _tools_metadata.items():
        tool_def: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": metadata["name"],
                "description": metadata["description"],
            }
        }
        if metadata.get("parameters"):
            tool_def["function"]["parameters"] = metadata["parameters"]
        tools.append(tool_def)

    return tools


# ---------------------------------------------------------------------------
# 内置工具注册
# ---------------------------------------------------------------------------

def _register_builtin_tools():
    """注册内置工具"""

    async def record_manager_decision_tool(
        decision: str,
        message: str,
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = execution_context or {}
        return {
            "status": "RECORDED",
            "decision": decision,
            "message": message,
            "event_id": context.get("event_id"),
            "task_id": context.get("task_id"),
        }

    register_tool(
        "record_manager_decision",
        record_manager_decision_tool,
        description="记录值班经理批准的高风险运营决策",
        parameters={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["decision", "message"],
        },
    )

    # 短信工具
    async def send_sms_tool(phone: str, message: str, priority: str = "normal") -> Dict[str, Any]:
        from .sms_client import send_sms
        severity = "P1" if priority == "high" else "P2"
        result = await send_sms(phone, message, severity)
        return {**result, "priority": priority}

    register_tool(
        "send_sms",
        send_sms_tool,
        description="发送短信",
        parameters={
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "手机号"},
                "message": {"type": "string", "description": "短信内容"},
                "priority": {"type": "string", "enum": ["normal", "high"], "description": "优先级"}
            },
            "required": ["phone", "message"]
        }
    )

    # 告警工具
    async def send_alert_tool(message: str, level: str = "warning") -> Dict[str, Any]:
        from .sms_client import send_alert
        return cast(Dict[str, Any], await send_alert(message, level))

    register_tool(
        "send_alert",
        send_alert_tool,
        description="发送告警通知",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "告警内容"},
                "level": {"type": "string", "enum": ["info", "warning", "critical"], "description": "告警级别"}
            },
            "required": ["message"]
        }
    )

    async def send_in_app_alert_tool(
        message: str,
        level: str = "warning",
        recipient_scope: str = "SESSION",
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = execution_context or {}
        database = context.get("_database")
        if database is None:
            raise RuntimeError("in-app alert database is unavailable")
        from ..core.simulator_outbox import (
            SimulatorRecipientsNotReady,
            validate_frozen_simulator_targets,
        )
        from ..knowledge.push_logger import write_push_log

        severity = {"critical": "P0", "warning": "P1", "info": "P2"}.get(level, "P2")
        evidence_snapshot = context.get("evidence_snapshot")
        if not isinstance(evidence_snapshot, dict):
            evidence_snapshot = {}
        delivery = evidence_snapshot.get("delivery")
        if not isinstance(delivery, dict):
            delivery = {}
        frozen_targets = delivery.get("targets")
        if not isinstance(frozen_targets, list):
            frozen_targets = []
        fanout_requested = (
            str(recipient_scope or "").upper() == "EVENT_PARTICIPANTS"
            or str(delivery.get("scope") or "").upper() == "EVENT_PARTICIPANTS"
        )
        if fanout_requested:
            invalid_snapshot = (
                str(delivery.get("scope") or "").upper() != "EVENT_PARTICIPANTS"
                or str(delivery.get("channel") or "").upper()
                != "WECOM_SIMULATOR_OUTBOX"
                or not frozen_targets
            )
            unique_targets: list[dict[str, Any]] = []
            seen_user_ids: set[str] = set()
            for target in frozen_targets:
                if not isinstance(target, dict):
                    invalid_snapshot = True
                    continue
                user_id = str(target.get("user_id") or "").strip()
                session_id = str(target.get("session_id") or "").strip()
                if not user_id or not session_id or user_id in seen_user_ids:
                    invalid_snapshot = True
                    continue
                seen_user_ids.add(user_id)
                unique_targets.append(target)
            if delivery.get("target_count") != len(unique_targets):
                invalid_snapshot = True
            if invalid_snapshot:
                raise SimulatorRecipientsNotReady(
                    [
                        {
                            "display_name": "冻结收件人",
                            "reason_code": "FROZEN_TARGETS_INVALID",
                            "reason": "审批缺少完整且一致的模拟器收件人证据",
                        }
                    ]
                )
            await validate_frozen_simulator_targets(
                database,
                venue_id=context.get("venue_id") or "",
                targets=unique_targets,
            )
            delivered = []
            approval_id = context.get("approval_id") or ""
            for target in unique_targets:
                user_id = str(target["user_id"])
                session_id = str(target["session_id"])
                push_id = await write_push_log(
                    msg_id=approval_id,
                    from_user=context.get("user_id") or "system",
                    raw_text=message,
                    event_type="企微模拟器通知",
                    severity=severity,
                    stage1_triggered=False,
                    hit_keywords=["controlled_action", "wecom_simulator_outbox"],
                    stage2_triggered=None,
                    llm_confidence=None,
                    trace_id=context.get("trace_id") or "",
                    venue_id=context.get("venue_id") or "",
                    database=database,
                    channel="WECOM_SIMULATOR_OUTBOX",
                    recipient=f"session:{session_id}",
                    delivery_status="DELIVERED",
                    idempotency_key=f"{approval_id}:recipient:{user_id}",
                )
                delivered.append(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "push_id": push_id,
                    }
                )
            return {
                "status": "DELIVERED",
                "channel": "WECOM_SIMULATOR_OUTBOX",
                "recipient_scope": recipient_scope,
                "target_count": len(unique_targets),
                "delivered_count": len(delivered),
                "deliveries": delivered,
            }

        recipient = f"session:{context.get('session_id') or 'unknown'}"
        push_id = await write_push_log(
            msg_id=context.get("approval_id") or "",
            from_user=context.get("user_id") or "system",
            raw_text=message,
            event_type="站内告警",
            severity=severity,
            stage1_triggered=False,
            hit_keywords=["controlled_action", "in_app"],
            stage2_triggered=None,
            llm_confidence=None,
            trace_id=context.get("trace_id") or "",
            venue_id=context.get("venue_id") or "",
            database=database,
            channel="in_app",
            recipient=recipient,
            delivery_status="DELIVERED",
            idempotency_key=context.get("approval_id") or None,
        )
        return {
            "status": "DELIVERED",
            "channel": "in_app",
            "recipient": recipient,
            "push_id": push_id,
        }

    register_tool(
        "send_in_app_alert",
        send_in_app_alert_tool,
        description="发送站内告警",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "告警内容"},
                "level": {
                    "type": "string",
                    "enum": ["info", "warning", "critical"],
                    "description": "告警级别",
                },
            },
            "required": ["message"],
        },
    )

    # 记忆搜索
    async def search_memory_tool(
        query: str,
        limit: int = 5,
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from ..knowledge.vector_store import get_vector_client
        venue_id = str((execution_context or {}).get("venue_id") or "").strip()
        if not venue_id:
            raise ValueError("venue_id is required for memory search")
        vs = get_vector_client()
        if vs is None:
            return {"results": [], "query": query, "error": "vector store not available"}
        results = vs.query_experience(query, top_k=limit, venue_id=venue_id)
        return {"results": results, "query": query}

    register_tool(
        "search_memory",
        search_memory_tool,
        description="搜索向量内存",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "limit": {"type": "integer", "description": "返回结果数量"}
            },
            "required": ["query"]
        }
    )

    # 记忆写入
    async def write_memory_tool(
        content: str,
        metadata: Optional[Dict] = None,
        execution_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        venue_id = str((execution_context or {}).get("venue_id") or "").strip()
        if not venue_id:
            raise ValueError("venue_id is required for memory writes")
        from ..tools.llm_wrapper import sanitize_llm_output
        data, warns = sanitize_llm_output(
            {"content": content, "metadata": metadata or {}},
            "write_memory",
        )
        if not data or not data.get("content"):
            return {"success": False, "content": content, "error": "content rejected by sanitizer"}
        content = data["content"]
        metadata = {**(data.get("metadata", {}) or {}), "venue_id": venue_id}
        from ..knowledge.vector_store import get_vector_client
        vs = get_vector_client()
        if vs is None:
            return {"success": False, "content": content, "error": "vector store not available"}
        import uuid
        vs.upsert_experience(content=content, metadata=metadata or {}, doc_id=uuid.uuid4().hex[:12])
        return {"success": True, "content": content}

    register_tool(
        "write_memory",
        write_memory_tool,
        description="写入向量内存",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要写入的内容"},
                "metadata": {"type": "object", "description": "元数据"}
            },
            "required": ["content"]
        }
    )

    logger.info(f"[ToolExecutor] 内置工具注册完成，共 {len(_tools)} 个工具")


# 启动时自动注册内置工具
_register_builtin_tools()
