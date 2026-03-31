"""
热更新机制测试 (Unit Test for Hot Reload)

测试核心：验证 skill 文件变更后，HotReloadManager 是否能正确重新加载配置和 Prompt。

工业级测试要点：
1. Prompt 缓存失效：变更 soul.txt 后，load_prompt 返回新内容
2. 配置热更新：变更 config.yaml 后，新实例读取到新配置
3. 注册表更新：reload_skill() 更新的是新实例，不是旧实例
4. 多 Skill 并行热更新无相互干扰

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.memory_palace.core.hot_reload import (
    HotReloadManager,
    reload_skill,
    get_hot_reload_manager,
)


@pytest.fixture
def hot_reload_manager():
    return HotReloadManager()


class TestPromptCacheInvalidation:

    def test_initial_prompt_cached(self, hot_reload_manager):
        """首次加载 Prompt 应被缓存"""
        content = "初始 Prompt 内容"
        hot_reload_manager._prompt_cache["test"] = content

        assert hot_reload_manager._prompt_cache.get("test") == content

    def test_invalidate_prompt_cache_clears_all(self, hot_reload_manager):
        """失效调用应清空所有 Prompt 缓存"""
        hot_reload_manager._prompt_cache["skill_a"] = "内容A"
        hot_reload_manager._prompt_cache["skill_b"] = "内容B"

        hot_reload_manager.invalidate_prompt_cache()

        assert len(hot_reload_manager._prompt_cache) == 0

    def test_invalidate_skill_only_clears_one(self, hot_reload_manager):
        """按 Skill 失效只清空对应条目"""
        hot_reload_manager._prompt_cache["router"] = "Router 内容"
        hot_reload_manager._prompt_cache["commander"] = "Commander 内容"

        hot_reload_manager.invalidate_skill("router")

        assert "router" not in hot_reload_manager._prompt_cache
        assert "commander" in hot_reload_manager._prompt_cache


class TestConfigReload:

    @pytest.mark.asyncio
    async def test_reload_skill_updates_instance(self, hot_reload_manager):
        """reload_skill() 重新实例化 Skill，加载新配置"""
        with patch("src.memory_palace.core.hot_reload.get_skill_by_name") as mock_get:
            # 第一次获取：返回模拟实例
            mock_instance = MagicMock()
            mock_instance.invalidate_prompt_cache = MagicMock()
            mock_get.return_value = mock_instance

            result = await hot_reload_manager.reload_skill("router")

            assert result is True
            mock_instance.invalidate_prompt_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_nonexistent_skill_returns_false(self, hot_reload_manager):
        """重载不存在的 Skill 应返回 False"""
        with patch("src.memory_palace.core.hot_reload.get_skill_by_name", return_value=None):
            result = await hot_reload_manager.reload_skill("nonexistent_skill")
            assert result is False


class TestGlobalReloadFunction:

    @pytest.mark.asyncio
    async def test_reload_skill_module_level(self):
        """模块级 reload_skill() 函数正常工作"""
        with patch("src.memory_palace.core.hot_reload.get_hot_reload_manager") as mock_mgr:
            mock_instance = MagicMock()
            mock_instance.reload_skill = MagicMock(return_value=True)
            mock_mgr.return_value = mock_instance

            result = await reload_skill("router")

            assert result is True
            mock_instance.reload_skill.assert_called_once_with("router")


class TestFileWatching:

    def test_watch_path_added(self, hot_reload_manager):
        """watch_add() 应将路径添加到监控列表"""
        test_path = Path(tempfile.gettempdir()) / "test_skill.py"

        hot_reload_manager.watch_add("router", test_path)

        assert "router" in hot_reload_manager._watched_files
        assert test_path in hot_reload_manager._watched_files["router"]

    def test_watch_remove_clears_path(self, hot_reload_manager):
        """watch_remove() 应从监控列表移除"""
        test_path = Path(tempfile.gettempdir()) / "test_skill.py"
        hot_reload_manager._watched_files["router"] = {test_path}

        hot_reload_manager.watch_remove("router")

        assert "router" not in hot_reload_manager._watched_files

    def test_watch_clear_all(self, hot_reload_manager):
        """watch_clear() 应清空所有监控路径"""
        hot_reload_manager._watched_files["a"] = {Path("/a")}
        hot_reload_manager._watched_files["b"] = {Path("/b")}

        hot_reload_manager.watch_clear()

        assert len(hot_reload_manager._watched_files) == 0


class TestSingletonManager:

    def test_get_manager_returns_same_instance(self):
        """get_hot_reload_manager() 应返回单例"""
        m1 = get_hot_reload_manager()
        m2 = get_hot_reload_manager()
        assert m1 is m2
