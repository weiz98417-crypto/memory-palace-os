"""
工具执行器 (ToolExecutor) 单元测试

覆盖: 工具注册、执行、列表、错误处理

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
from src.memory_palace.tools.tool_executor import (
    register_tool,
    get_tool,
    list_tools,
    execute_tool,
)


class TestToolExecutor:

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试后从全局 _tools 中清理测试注册的工具"""
        from src.memory_palace.tools import tool_executor as te
        builtins = {"send_sms", "send_alert", "search_memory", "write_memory"}
        yield
        for key in list(te._tools.keys()):
            if key not in builtins:
                del te._tools[key]
                if key in te._tools_metadata:
                    del te._tools_metadata[key]

    def test_register_tool(self):
        """注册一个工具"""
        async def my_tool(x: str) -> dict:
            return {"result": x}

        register_tool("my_tool", my_tool, description="测试工具")
        tool = get_tool("my_tool")
        assert tool is not None
        assert callable(tool)

    def test_list_tools_includes_builtins(self):
        """工具列表包含内置工具"""
        tools = list_tools()
        assert isinstance(tools, dict)
        assert "send_sms" in tools
        assert "write_memory" in tools

    def test_list_tools_after_register(self):
        """注册后工具出现在列表中"""
        async def tool_a(): pass
        register_tool("tool_a", tool_a, description="Tool A")
        tools = list_tools()
        assert "tool_a" in tools

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self):
        """执行不存在的工具返回 status='error'"""
        result = await execute_tool("nonexistent_tool_xyz", {})
        assert result["status"] == "error"

    def test_get_tool_nonexistent(self):
        """获取不存在的工具返回 None"""
        result = get_tool("nonexistent")
        assert result is None

    def test_register_preserves_metadata(self):
        """工具注册保留参数 schema"""
        async def search_tool(query: str, limit: int = 10): return {}
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        }
        register_tool("search_test", search_tool, description="Search", parameters=schema)
        from src.memory_palace.tools import tool_executor as te
        stored = te._tools_metadata["search_test"]
        assert stored["parameters"]["required"] == ["query"]
