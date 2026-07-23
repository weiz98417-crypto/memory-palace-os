"""
热更新机制测试 (Unit Test for Hot Reload)

测试核心：验证 skill 文件变更后，HotReloadManager 是否能正确重新加载配置和 Prompt。

当前 API（SkillCache + HotReloadManager 异步模式）：
  cache.get / set / invalidate / notify_update
  manager.load_soul / load_prompts / reload_skill / start_watching

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from src.memory_palace.core.hot_reload import (
    HotReloadManager,
    SkillCache,
    SkillReloadResult,
    reload_skill,
    get_hot_reload_manager,
)


@pytest.fixture
def cache():
    return SkillCache()


@pytest.fixture
def hot_reload_manager():
    return HotReloadManager()


class TestSkillCache:
    """SkillCache 基础 CRUD 测试"""

    def test_set_and_get(self, cache):
        cache.set("router", "soul.txt", "Router 灵魂内容")
        assert cache.get("router", "soul.txt") == "Router 灵魂内容"

    def test_get_missing(self, cache):
        assert cache.get("nonexistent", "file.txt") is None

    def test_invalidate_skill(self, cache):
        cache.set("router", "a.txt", "内容A")
        cache.set("router", "b.txt", "内容B")
        cache.set("commander", "a.txt", "内容C")

        cache.invalidate("router")
        assert cache.get("router", "a.txt") is None
        assert cache.get("router", "b.txt") is None
        assert cache.get("commander", "a.txt") == "内容C"

    def test_invalidate_single_file(self, cache):
        cache.set("router", "a.txt", "内容A")
        cache.set("router", "b.txt", "内容B")

        cache.invalidate("router", "a.txt")
        assert cache.get("router", "a.txt") is None
        assert cache.get("router", "b.txt") == "内容B"

    def test_hash_tracking(self, cache):
        cache.set("router", "soul.txt", "hello")
        h = cache.get_hash("router", "soul.txt")
        assert h is not None
        assert len(h) == 64  # SHA256 hex

    def test_version_tracking(self, cache):
        from src.memory_palace.core.hot_reload import SkillVersion
        v = SkillVersion(version="1.2.3", file_hash="abc", loaded_at=0, content="test")
        cache.set_version("router", v)
        assert cache.get_version("router").version == "1.2.3"


class TestHotReloadManagerReload:

    @pytest.mark.asyncio
    async def test_reload_skill_returns_result(self, hot_reload_manager):
        """reload_skill() 返回 SkillReloadResult"""
        result = await hot_reload_manager.reload_skill("nonexistent_skill")
        assert isinstance(result, SkillReloadResult)
        from src.memory_palace.core.hot_reload import ReloadStatus
        assert result.status == ReloadStatus.FAILED

    @pytest.mark.asyncio
    async def test_reload_all_skills(self, hot_reload_manager):
        """reload_all() 不崩溃"""
        results = await hot_reload_manager.reload_all()
        assert isinstance(results, list)


class TestGlobalReloadFunction:

    @pytest.mark.asyncio
    async def test_module_level_reload_skill(self):
        """模块级 reload_skill() 返回 SkillReloadResult"""
        result = await reload_skill("router")
        assert isinstance(result, SkillReloadResult)


class TestSingletonManager:

    def test_get_manager_returns_same_instance(self):
        """get_hot_reload_manager() 返回单例"""
        m1 = get_hot_reload_manager()
        m2 = get_hot_reload_manager()
        assert m1 is m2
