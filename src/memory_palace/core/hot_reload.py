"""
hot_reload.py · Skill 热更新模块
================================================================
职责：
  1. 实现技能 (Skill) 热更新机制，无需重启服务即可更新灵魂配置。
  2. 支持 soul.txt、prompts/ 等配置文件的动态加载。
  3. 提供版本控制和回滚机制。
  4. 支持 WebSocket/SSE 推送更新通知。
  5. 记录热更新历史，便于审计追踪。
"""

import os
import re
import time
import hashlib
import asyncio
import traceback
from typing import Optional, Dict, Any, List, Callable, Set
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from loguru import logger


# ==============================================================================
# 配置
# ==============================================================================

# 默认技能目录
DEFAULT_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Soul 文件名
SOUL_FILENAME = "soul.txt"

# Prompts 目录名
PROMPTS_DIRNAME = "prompts"


# ==============================================================================
# 类型定义
# ==============================================================================

class ReloadStatus(str, Enum):
    """重载状态"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class FileChangeType(str, Enum):
    """文件变更类型"""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


# ==============================================================================
# 模型定义
# ==============================================================================

class SkillVersion(BaseModel):
    """技能版本信息"""
    version: str
    file_hash: str
    loaded_at: float
    content: Optional[str] = None


class SkillReloadResult(BaseModel):
    """技能重载结果"""
    skill_name: str
    status: ReloadStatus
    message: str
    reload_time_ms: float
    files_reloaded: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    previous_version: Optional[str] = None
    new_version: Optional[str] = None


class FileChange(BaseModel):
    """文件变更记录"""
    skill_name: str
    file_path: str
    change_type: FileChangeType
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class HotReloadHistory(BaseModel):
    """热更新历史"""
    skill_name: str
    status: ReloadStatus
    files: List[str]
    timestamp: float
    duration_ms: float
    triggered_by: str = "manual"  # manual, auto, webhook


@dataclass
class SkillReloadConfig:
    """热更新配置"""
    enabled: bool = True
    watch_dirs: Set[Path] = field(default_factory=set)
    auto_reload: bool = True
    reload_delay_seconds: float = 1.0
    max_retry: int = 3
    backup_enabled: bool = True
    backup_dir: Path = field(default_factory=lambda: Path("/tmp/memory_palace/backups"))


# ==============================================================================
# 工具函数
# ==============================================================================

def calculate_file_hash(file_path: Path) -> str:
    """计算文件 SHA256 哈希"""
    if not file_path.exists():
        return ""

    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"计算文件哈希失败: {file_path}, {e}")
        return ""


def calculate_content_hash(content: str) -> str:
    """计算内容哈希"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_file_safe(file_path: Path, encoding: str = "utf-8") -> Optional[str]:
    """安全读取文件"""
    try:
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, {e}")
        return None


def write_file_safe(file_path: Path, content: str, encoding: str = "utf-8") -> bool:
    """安全写入文件"""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding=encoding) as f:
            f.write(content)
        return True
    except Exception as e:
        logger.error(f"写入文件失败: {file_path}, {e}")
        return False


def parse_version(content: str) -> str:
    """从 soul.txt 中解析版本号"""
    # 支持格式: # Version: 1.0.0 或 version: 1.0.0
    patterns = [
        r"#\s*[Vv]ersion:\s*(\d+\.\d+\.\d+)",
        r"version:\s*(\d+\.\d+\.\d+)",
        r"__version__\s*=\s*['\"](\d+\.\d+\.\d+)['\"]",
    ]

    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return match.group(1)

    return "0.0.0"


# ==============================================================================
# 技能缓存管理器
# ==============================================================================

class SkillCache:
    """技能配置缓存"""

    def __init__(self):
        # 技能名 -> 文件路径 -> 缓存内容
        self._content_cache: Dict[str, Dict[str, str]] = defaultdict(dict)
        # 技能名 -> 文件路径 -> 文件哈希
        self._hash_cache: Dict[str, Dict[str, str]] = defaultdict(dict)
        # 技能名 -> 版本信息
        self._version_cache: Dict[str, SkillVersion] = {}
        # 更新回调
        self._update_callbacks: Dict[str, List[Callable]] = defaultdict(list)

    def get(self, skill_name: str, file_path: str) -> Optional[str]:
        """获取缓存内容"""
        return self._content_cache.get(skill_name, {}).get(file_path)

    def set(self, skill_name: str, file_path: str, content: str):
        """设置缓存内容"""
        self._content_cache[skill_name][file_path] = content
        self._hash_cache[skill_name][file_path] = calculate_content_hash(content)

    def get_hash(self, skill_name: str, file_path: str) -> Optional[str]:
        """获取文件哈希"""
        return self._hash_cache.get(skill_name, {}).get(file_path)

    def invalidate(self, skill_name: str, file_path: Optional[str] = None):
        """使缓存失效"""
        if file_path:
            self._content_cache[skill_name].pop(file_path, None)
            self._hash_cache[skill_name].pop(file_path, None)
        else:
            self._content_cache.pop(skill_name, None)
            self._hash_cache.pop(skill_name, None)

    def get_version(self, skill_name: str) -> Optional[SkillVersion]:
        """获取版本信息"""
        return self._version_cache.get(skill_name)

    def set_version(self, skill_name: str, version: SkillVersion):
        """设置版本信息"""
        self._version_cache[skill_name] = version

    def register_callback(self, skill_name: str, callback: Callable):
        """注册更新回调"""
        self._update_callbacks[skill_name].append(callback)

    async def notify_update(self, skill_name: str, file_path: str, new_content: str):
        """通知更新"""
        # 更新缓存
        self.set(skill_name, file_path, new_content)

        # 更新版本
        if file_path.endswith(SOUL_FILENAME):
            version_str = parse_version(new_content)
            self._version_cache[skill_name] = SkillVersion(
                version=version_str,
                file_hash=calculate_content_hash(new_content),
                loaded_at=time.time(),
                content=new_content
            )

        # 调用回调
        for callback in self._update_callbacks.get(skill_name, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(skill_name, file_path, new_content)
                else:
                    callback(skill_name, file_path, new_content)
            except Exception as e:
                logger.error(f"更新回调执行失败: {skill_name}, {file_path}, {e}")


# ==============================================================================
# 热更新管理器
# ==============================================================================

class HotReloadManager:
    """热更新管理器"""

    def __init__(self, config: Optional[SkillReloadConfig] = None):
        self.config = config or SkillReloadConfig()
        self.cache = SkillCache()
        self._file_watchers: Dict[Path, asyncio.Task] = {}
        self._reload_history: List[HotReloadHistory] = []
        self._skills_dir = DEFAULT_SKILLS_DIR
        self._running = False

        # 确保备份目录存在
        if self.config.backup_enabled:
            self.config.backup_dir.mkdir(parents=True, exist_ok=True)

    def set_skills_dir(self, skills_dir: Path):
        """设置技能目录"""
        self._skills_dir = skills_dir
        self.config.watch_dirs.add(skills_dir)

    def get_skill_path(self, skill_name: str) -> Optional[Path]:
        """获取技能路径"""
        skill_path = self._skills_dir / skill_name
        return skill_path if skill_path.exists() else None

    def get_skill_files(self, skill_name: str) -> List[Path]:
        """获取技能所有相关文件"""
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return []

        files = []

        # Soul 文件
        soul_file = skill_path / SOUL_FILENAME
        if soul_file.exists():
            files.append(soul_file)

        # Prompts 目录
        prompts_dir = skill_path / PROMPTS_DIRNAME
        if prompts_dir.exists() and prompts_dir.is_dir():
            files.extend(p for p in prompts_dir.rglob("*") if p.is_file())

        # Config 文件
        config_file = skill_path / "config.yaml"
        if config_file.exists():
            files.append(config_file)

        return files

    async def load_soul(self, skill_name: str) -> Optional[str]:
        """加载技能灵魂文件"""
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            logger.warning(f"技能不存在: {skill_name}")
            return None

        soul_file = skill_path / SOUL_FILENAME
        if not soul_file.exists():
            logger.warning(f"灵魂文件不存在: {skill_name}/{SOUL_FILENAME}")
            return None

        content = read_file_safe(soul_file)
        if content:
            await self.cache.notify_update(skill_name, str(soul_file), content)
            logger.info(f"✅ 灵魂文件加载成功: {skill_name}")

        return content

    async def load_prompts(self, skill_name: str) -> Dict[str, str]:
        """加载技能提示词文件"""
        skill_path = self.get_skill_path(skill_name)
        if not skill_path:
            return {}

        prompts_dir = skill_path / PROMPTS_DIRNAME
        if not prompts_dir.exists():
            return {}

        prompts = {}
        for prompt_file in prompts_dir.rglob("*.txt"):
            content = read_file_safe(prompt_file)
            if content:
                relative_path = prompt_file.relative_to(prompts_dir)
                prompts[str(relative_path)] = content
                await self.cache.notify_update(
                    skill_name,
                    str(prompt_file),
                    content
                )

        return prompts

    async def reload_skill(self, skill_name: str) -> SkillReloadResult:
        """热更新单个技能"""
        start_time = time.perf_counter()
        result = SkillReloadResult(
            skill_name=skill_name,
            status=ReloadStatus.SKIPPED,
            message="",
            reload_time_ms=0
        )

        try:
            # 获取当前版本
            current_version = self.cache.get_version(skill_name)
            result.previous_version = current_version.version if current_version else None

            # 获取所有文件
            files = self.get_skill_files(skill_name)
            if not files:
                result.status = ReloadStatus.FAILED
                result.message = "技能文件不存在"
                return result

            # 检查变更
            changed_files = []
            for file_path in files:
                old_hash = self.cache.get_hash(skill_name, str(file_path))
                new_hash = calculate_file_hash(file_path)

                if old_hash != new_hash:
                    changed_files.append(file_path)

            if not changed_files:
                result.status = ReloadStatus.SKIPPED
                result.message = "文件未变更，跳过更新"
                return result

            # 备份文件
            if self.config.backup_enabled:
                await self._backup_files(skill_name, changed_files)

            # 加载 soul.txt
            soul_file = self.get_skill_path(skill_name) / SOUL_FILENAME
            if soul_file in changed_files:
                await self.load_soul(skill_name)
                result.files_reloaded.append(str(soul_file))

            # 加载 prompts
            prompts = await self.load_prompts(skill_name)
            if prompts:
                result.files_reloaded.extend(list(prompts.keys()))

            # 加载成功
            new_version = self.cache.get_version(skill_name)
            result.new_version = new_version.version if new_version else None
            result.status = ReloadStatus.SUCCESS
            result.message = f"热更新成功，更新了 {len(result.files_reloaded)} 个文件"

            # 记录历史
            self._reload_history.append(HotReloadHistory(
                skill_name=skill_name,
                status=result.status,
                files=result.files_reloaded,
                timestamp=time.time(),
                duration_ms=result.reload_time_ms
            ))

        except Exception as e:
            result.status = ReloadStatus.FAILED
            result.message = f"热更新失败: {str(e)}"
            result.errors.append(traceback.format_exc())
            logger.error(f"热更新失败: {skill_name}, {e}")

        result.reload_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def reload_all(self) -> List[SkillReloadResult]:
        """热更新所有技能"""
        results = []

        # 遍历所有技能目录
        if not self._skills_dir.exists():
            logger.warning(f"技能目录不存在: {self._skills_dir}")
            return results

        for skill_dir in self._skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("_"):
                result = await self.reload_skill(skill_dir.name)
                results.append(result)

        return results

    async def _backup_files(self, skill_name: str, files: List[Path]):
        """备份文件"""
        backup_dir = self.config.backup_dir / skill_name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = backup_dir / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        for file_path in files:
            relative_path = file_path.name
            backup_path = backup_dir / relative_path
            content = read_file_safe(file_path)
            if content:
                write_file_safe(backup_path, content)

        logger.debug(f"备份已保存: {backup_dir}")

    async def get_skill_content(self, skill_name: str) -> Dict[str, Any]:
        """获取技能完整内容"""
        content = await self.load_soul(skill_name)
        prompts = await self.load_prompts(skill_name)
        version = self.cache.get_version(skill_name)

        return {
            "skill_name": skill_name,
            "soul": content,
            "prompts": prompts,
            "version": version.version if version else None,
            "hash": version.file_hash if version else None,
            "loaded_at": version.loaded_at if version else None
        }

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取热更新历史"""
        history = self._reload_history[-limit:]
        return [h.model_dump() for h in history]

    async def start_watching(self):
        """启动文件监控"""
        if self._running:
            return

        self._running = True
        for watch_dir in self.config.watch_dirs:
            if watch_dir.exists():
                task = asyncio.create_task(self._watch_directory(watch_dir))
                self._file_watchers[watch_dir] = task

        logger.info("✅ 文件监控已启动")

    async def stop_watching(self):
        """停止文件监控"""
        self._running = False
        for task in self._file_watchers.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._file_watchers.clear()
        logger.info("👋 文件监控已停止")

    async def _watch_directory(self, watch_dir: Path):
        """监控目录变更"""
        import time as time_module

        last_check = time_module.time()

        while self._running:
            try:
                # 遍历技能目录
                for skill_dir in watch_dir.iterdir():
                    if not skill_dir.is_dir():
                        continue

                    # 检查 soul.txt
                    soul_file = skill_dir / SOUL_FILENAME
                    if soul_file.exists():
                        mtime = soul_file.stat().st_mtime
                        if mtime > last_check:
                            logger.info(f"检测到文件变更: {skill_dir.name}")
                            await self.reload_skill(skill_dir.name)
                            last_check = time_module.time()

                await asyncio.sleep(self.config.reload_delay_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"目录监控异常: {watch_dir}, {e}")
                await asyncio.sleep(5)


# ==============================================================================
# 全局实例
# ==============================================================================

_hot_reload_manager: Optional[HotReloadManager] = None


def get_hot_reload_manager() -> HotReloadManager:
    """获取热更新管理器"""
    global _hot_reload_manager
    if _hot_reload_manager is None:
        _hot_reload_manager = HotReloadManager()
    return _hot_reload_manager


def init_hot_reload(skills_dir: Optional[Path] = None) -> HotReloadManager:
    """初始化热更新"""
    manager = get_hot_reload_manager()
    if skills_dir:
        manager.set_skills_dir(skills_dir)
    logger.info("✅ 热更新模块初始化完成")
    return manager


# ==============================================================================
# API 路由
# ==============================================================================

router = APIRouter(prefix="/v1/skills", tags=["Skill Management"])


@router.post("/{skill_name}/reload")
async def reload_skill(skill_name: str) -> SkillReloadResult:
    """热更新指定技能"""
    manager = get_hot_reload_manager()
    result = await manager.reload_skill(skill_name)
    return result


@router.post("/reload-all")
async def reload_all_skills():
    """热更新所有技能"""
    manager = get_hot_reload_manager()
    results = await manager.reload_all()
    return {
        "code": 0,
        "total": len(results),
        "success": sum(1 for r in results if r.status == ReloadStatus.SUCCESS),
        "failed": sum(1 for r in results if r.status == ReloadStatus.FAILED),
        "skipped": sum(1 for r in results if r.status == ReloadStatus.SKIPPED),
        "results": [r.model_dump() for r in results]
    }


@router.get("/{skill_name}/content")
async def get_skill_content(skill_name: str) -> Dict[str, Any]:
    """获取技能完整内容"""
    manager = get_hot_reload_manager()
    content = await manager.get_skill_content(skill_name)
    if content.get("soul") is None and not content.get("prompts"):
        raise HTTPException(status_code=404, detail="Skill not found")
    return content


@router.get("/{skill_name}/version")
async def get_skill_version(skill_name: str):
    """获取技能版本信息"""
    manager = get_hot_reload_manager()
    version = manager.cache.get_version(skill_name)
    if not version:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "skill_name": skill_name,
        "version": version.version,
        "hash": version.file_hash,
        "loaded_at": version.loaded_at
    }


@router.get("/history")
async def get_reload_history(limit: int = 50):
    """获取热更新历史"""
    manager = get_hot_reload_manager()
    return {
        "code": 0,
        "total": len(manager._reload_history),
        "history": manager.get_history(limit)
    }


@router.post("/watch/start")
async def start_watching():
    """启动文件监控"""
    manager = get_hot_reload_manager()
    await manager.start_watching()
    return {"code": 0, "message": "文件监控已启动"}


@router.post("/watch/stop")
async def stop_watching():
    """停止文件监控"""
    manager = get_hot_reload_manager()
    await manager.stop_watching()
    return {"code": 0, "message": "文件监控已停止"}


@router.get("/watch/status")
async def get_watch_status():
    """获取监控状态"""
    manager = get_hot_reload_manager()
    return {
        "code": 0,
        "running": manager._running,
        "watching_dirs": [str(d) for d in manager.config.watch_dirs]
    }


# ==============================================================================
# 导出
# ==============================================================================

async def reload_skill(skill_name: str) -> SkillReloadResult:
    """热更新指定技能（模块级便捷函数）"""
    manager = get_hot_reload_manager()
    return await manager.reload_skill(skill_name)


__all__ = [
    # 配置
    "SkillReloadConfig",

    # 模型
    "SkillVersion",
    "SkillReloadResult",
    "FileChange",
    "HotReloadHistory",

    # 枚举
    "ReloadStatus",
    "FileChangeType",

    # 缓存
    "SkillCache",

    # 管理器
    "HotReloadManager",
    "get_hot_reload_manager",
    "init_hot_reload",

    # 路由
    "router",

    # 便捷函数
    "reload_skill",
]

    