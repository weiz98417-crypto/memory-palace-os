"""
工具执行器 (Tool Executor)

核心职责:
1. 统一管理所有工具的注册和执行
2. 集成权限引擎，所有工具调用都经过权限检查
3. 提供工具执行结果标准化

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import json
from typing import Any, Callable, Dict, Optional

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


async def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
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

        # 判断是 async 还是 sync 函数
        if asyncio.iscoroutinefunction(func):
            result = await func(**args)
        else:
            result = func(**args)

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
            "message": str(e)
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
    return await engine.check_and_execute(tool_name, args, context)


def get_openai_tools_format() -> list:
    """
    获取 OpenAI tools API 格式的工具定义

    Returns:
        OpenAI compatible tools list
    """
    tools = []
    for name, metadata in _tools_metadata.items():
        tool_def = {
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

    # 短信工具
    async def send_sms_tool(phone: str, message: str, priority: str = "normal") -> Dict[str, Any]:
        from .sms_client import send_sms
        result = await send_sms(phone, message)
        return {"sent": True, "phone": phone, "priority": priority}

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
        result = await send_alert(message, level)
        return {"sent": True, "level": level, "message": message}

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

    # 记忆搜索
    async def search_memory_tool(query: str, limit: int = 5) -> Dict[str, Any]:
        from ..knowledge.vector_store import get_vector_client
        vs = get_vector_client()
        if vs is None:
            return {"results": [], "query": query, "error": "vector store not available"}
        results = vs.query_experience(query, top_k=limit)
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
    async def write_memory_tool(content: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        from ..tools.llm_wrapper import sanitize_llm_output
        data, warns = sanitize_llm_output(
            {"content": content, "metadata": metadata or {}},
            "write_memory",
        )
        if not data or not data.get("content"):
            return {"success": False, "content": content, "error": "content rejected by sanitizer"}
        content = data["content"]
        metadata = data.get("metadata", {})
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
