"""
安全文件操作 (SafeFileOps) 单元测试

覆盖: 路径遍历检测、文件操作接口、边界条件

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
from src.memory_palace.tools.file_ops import is_path_traversal, SafeFileOps


class TestPathTraversal:

    def test_normal_path_not_traversal(self):
        """正常相对路径不触发遍历检测"""
        assert is_path_traversal("data/input.txt") is False
        assert is_path_traversal("notes/test.md") is False
        assert is_path_traversal("output/subdir/result.json") is False
        assert is_path_traversal(".") is False

    def test_dot_dot_slash_blocked(self):
        """../ 和 ..\\ 被检测为遍历攻击"""
        assert is_path_traversal("../etc/passwd") is True
        assert is_path_traversal("..\\windows\\system32") is True

    def test_url_encoded_blocked(self):
        """URL 编码的 ../ 被检测"""
        assert is_path_traversal("%2e%2e/etc/passwd") is True
        assert is_path_traversal("%2e%2e\\etc") is True

    def test_double_dot_variants_blocked(self):
        """....// 和 ....\/ 变体被检测"""
        assert is_path_traversal("....//etc/passwd") is True
        assert is_path_traversal("....\\/etc") is True

    def test_deep_nested_traversal(self):
        """深层嵌套的遍历攻击被检测"""
        assert is_path_traversal("a/b/c/../../../etc/passwd") is True

    def test_empty_string(self):
        """空字符串不触发"""
        assert is_path_traversal("") is False

    def test_only_dots(self):
        """单独的 .. (没有斜杠) 在当前实现中不触发"""
        # is_path_traversal 检查 pattern in normalized, "../" 不在 ".." 中
        result = is_path_traversal("..")
        assert result is False  # 当前实现: 需要斜杠后缀


class TestSafeFileOpsValidatePath:

    def _make_ops(self):
        """创建 SafeFileOps 绕过 workspace_manager 初始化"""
        ops = object.__new__(SafeFileOps)
        ops.workspace_id = "test-ws"
        ops._workspace_manager = None
        ops._workspace = None
        return ops

    def test_normal_relative_path(self):
        """正常相对路径通过校验"""
        ops = self._make_ops()
        path = ops._validate_path("data/input.txt")
        # Windows 上 Path 会标准化为反斜杠
        assert "data" in str(path)
        assert "input.txt" in str(path)

    def test_absolute_path_rejected(self):
        """绝对路径被拒绝"""
        ops = self._make_ops()
        with pytest.raises(ValueError, match="绝对路径|路径遍历"):
            ops._validate_path("/etc/passwd")

    def test_dot_dot_traversal_rejected(self):
        """../ 遍历被拒绝"""
        ops = self._make_ops()
        with pytest.raises(ValueError, match="路径遍历攻击"):
            ops._validate_path("../etc/passwd")

    def test_windows_backslash_traversal_rejected(self):
        """Windows 反斜杠遍历被拒绝"""
        ops = self._make_ops()
        with pytest.raises(ValueError, match="路径遍历攻击"):
            ops._validate_path("..\\windows\\system32")

    def test_root_relative_rejected(self):
        """/ 开头的相对路径被拒绝"""
        ops = self._make_ops()
        with pytest.raises(ValueError, match="路径遍历攻击"):
            ops._validate_path("/data/file.txt")


class TestSafeFileOpsExists:

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_bad_path(self):
        """路径遍历攻击时 exists 返回 False 而非抛异常"""
        ops = SafeFileOps("test-ws")
        result = await ops.exists("../etc/passwd")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_nonexistent_file(self):
        """不存在的文件返回 False"""
        ops = SafeFileOps("test-ws")
        result = await ops.exists("nonexistent.txt")
        assert result is False
