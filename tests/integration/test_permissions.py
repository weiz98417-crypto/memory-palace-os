"""
Phase 2 权限引擎集成测试

验证：FREE/LOGGED/APPROVAL 三级权限、Container 接入

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest

from src.memory_palace.core.container import AppContainer
from src.memory_palace.core.permissions import PermissionEngine, SensitivityLevel


class TestPermissionEngine:

    def test_free_tool_level(self):
        """FREE 工具级别正确"""
        engine = PermissionEngine()
        p = engine.get_tool_permission("search_memory")
        assert p is not None and p.level == SensitivityLevel.FREE

    def test_logged_tool_level(self):
        """LOGGED 工具级别正确"""
        engine = PermissionEngine()
        p = engine.get_tool_permission("write_memory")
        assert p is not None and p.level == SensitivityLevel.LOGGED

    def test_approval_tool_level(self):
        """APPROVAL 工具级别正确"""
        engine = PermissionEngine()
        p = engine.get_tool_permission("send_sms")
        assert p is not None and p.level == SensitivityLevel.APPROVAL

    @pytest.mark.asyncio
    async def test_check_free_tool_returns_ok(self):
        """FREE 工具 check_and_execute 返回 ok"""
        engine = PermissionEngine()
        result = await engine.check_and_execute(
            tool_name="search_memory",
            args={"query": "test"},
            context={"session_id": "s1", "user_id": "u1"},
        )
        assert result["status"] in ("ok", "executed"), f"got {result['status']}"

    @pytest.mark.asyncio
    async def test_check_approval_tool_returns_pending(self):
        """APPROVAL 工具 check_and_execute 返回 pending_approval"""
        engine = PermissionEngine()
        result = await engine.check_and_execute(
            tool_name="send_sms",
            args={"message": "test", "phone": "13800000000"},
            context={"session_id": "s1", "user_id": "u1"},
        )
        assert result["status"] == "pending_approval"
        assert "approval_id" in result


class TestContainerPermissions:

    def test_container_has_permission_engine(self):
        """Container 暴露 permission_engine"""
        c = AppContainer()
        pe = c.permission_engine
        assert pe is not None
        c.reset()

    def test_container_has_tool_executor(self):
        """Container 暴露 tool_executor"""
        c = AppContainer()
        te = c.tool_executor
        assert te is not None
        c.reset()
