"""
工作区隔离 (Workspace Isolation) — STUB: Phase 4，待激活

核心职责:
1. 为每个复杂任务创建独立的隔离工作目录
2. 限制 Agent 的文件系统操作在 workspace 内
3. 任务完成后自动存档或销毁工作区
4. 防止路径遍历攻击

目录结构:
    data/workspaces/{workspace_id}/
        input/       # 输入文件
        output/      # 生成的文件
        temp/       # 临时文件 (完成时清理)
        metadata/   # 工作区元数据

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import json
import os
import shutil
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# 默认工作区根目录
WORKSPACE_ROOT = Path("data/workspaces")
ARCHIVES_ROOT = Path("data/workspaces/archives")


@dataclass
class Workspace:
    """
    隔离工作区

    每个 workspace 拥有独立的目录结构，Agent 文件操作被限制在此目录内。
    """
    workspace_id: str
    base_path: Path = field(default=WORKSPACE_ROOT)

    # 子目录
    INPUT_DIR = "input"
    OUTPUT_DIR = "output"
    TEMP_DIR = "temp"
    METADATA_DIR = "metadata"

    _active: bool = field(default=False, repr=False)

    @property
    def path(self) -> Path:
        """工作区根路径"""
        return self.base_path / self.workspace_id

    @property
    def input_path(self) -> Path:
        return self.path / self.INPUT_DIR

    @property
    def output_path(self) -> Path:
        return self.path / self.OUTPUT_DIR

    @property
    def temp_path(self) -> Path:
        return self.path / self.TEMP_DIR

    @property
    def metadata_path(self) -> Path:
        return self.path / self.METADATA_DIR

    @property
    def is_active(self) -> bool:
        return self._active

    async def create(self) -> "Workspace":
        """
        创建工作区目录结构

        Returns:
            self
        """
        if self._active:
            logger.warning(
                f"[Workspace] 工作区 {self.workspace_id} 已存在"
            )
            return self

        # 创建目录结构
        self.path.mkdir(parents=True, exist_ok=True)
        self.input_path.mkdir(exist_ok=True)
        self.output_path.mkdir(exist_ok=True)
        self.temp_path.mkdir(exist_ok=True)
        self.metadata_path.mkdir(exist_ok=True)

        # 写入元数据
        metadata = {
            "workspace_id": self.workspace_id,
            "created_at": time.time(),
            "created_at_iso": datetime.now().isoformat(),
            "status": "active"
        }
        (self.metadata_path / "info.json").write_text(
            json.dumps(metadata, ensure_ascii=False)
        )

        self._active = True
        logger.debug(f"[Workspace] 创建工作区: {self.workspace_id}")

        return self

    async def destroy(self, archive: bool = True) -> Optional[str]:
        """
        销毁工作区

        Args:
            archive: 是否先存档

        Returns:
            存档路径 (如果 archive=True)
        """
        if not self.path.exists():
            logger.debug(f"[Workspace] 工作区 {self.workspace_id} 不存在，跳过销毁")
            return None

        archive_path = None

        if archive:
            archive_path = await self._archive()

        # [修复] 使用 asyncio.to_thread 避免阻塞事件循环
        await asyncio.to_thread(shutil.rmtree, self.path)
        self._active = False

        logger.info(
            f"[Workspace] 销毁工作区: {self.workspace_id} "
            f"(archive: {archive_path or 'none'})"
        )

        return archive_path

    async def _archive(self) -> str:
        """
        打包存档工作区

        Returns:
            存档文件路径
        """
        archive_name = f"{self.workspace_id}.tar.gz"
        archive_path = ARCHIVES_ROOT / archive_name

        # 确保存档目录存在
        ARCHIVES_ROOT.mkdir(parents=True, exist_ok=True)

        # 创建 tar.gz
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(
                self.path,
                arcname=self.workspace_id
            )

        logger.debug(f"[Workspace] 存档工作区 {self.workspace_id} -> {archive_path}")

        return str(archive_path)

    def _validate_path(self, target_path: Path) -> Path:
        """
        验证路径在工作区内 (防止路径遍历)

        Args:
            target_path: 目标路径

        Returns:
            解析后的路径

        Raises:
            ValueError: 如果路径逃逸出工作区
        """
        # 解析绝对路径
        resolved = target_path.resolve()

        # 检查是否在工作区内
        worktree_resolved = self.path.resolve()

        if not str(resolved).startswith(str(worktree_resolved)):
            raise ValueError(
                f"路径逃逸攻击检测: {target_path} 不在工作区 {self.workspace_id} 内"
            )

        return resolved

    def get_input_path(self, filename: str) -> Path:
        """获取输入文件路径 (已验证)"""
        return self._validate_path(self.input_path / filename)

    def get_output_path(self, filename: str) -> Path:
        """获取输出文件路径 (已验证)"""
        return self._validate_path(self.output_path / filename)

    def get_temp_path(self, filename: str) -> Path:
        """获取临时文件路径 (已验证)"""
        return self._validate_path(self.temp_path / filename)

    def list_files(self, subdir: str = OUTPUT_DIR) -> List[str]:
        """列出子目录中的文件"""
        target = self.path / subdir
        if not target.exists():
            return []
        return [f.name for f in target.iterdir() if f.is_file()]

    def get_metadata(self) -> Dict[str, Any]:
        """获取工作区元数据"""
        info_file = self.metadata_path / "info.json"
        if info_file.exists():
            return json.loads(info_file.read_text())
        return {}


class WorkspaceManager:
    """
    工作区管理器 (全局单例)

    负责工作区的创建、销毁、查询
    """

    def __init__(self, root: Optional[Path] = None):
        self.root = root or WORKSPACE_ROOT
        self._workspaces: Dict[str, Workspace] = {}
        self._lock = asyncio.Lock()

    async def create_workspace(
        self,
        workspace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Workspace:
        """
        创建新工作区

        Args:
            workspace_id: 指定的工作区 ID (UUID)
            task_id: 关联的任务 ID
            session_id: 关联的会话 ID

        Returns:
            Workspace 对象
        """
        async with self._lock:
            # 生成工作区 ID
            ws_id = workspace_id or task_id or session_id or str(uuid.uuid4())

            if ws_id in self._workspaces:
                ws = self._workspaces[ws_id]
                if ws.is_active:
                    logger.debug(f"[WorkspaceManager] 返回已有工作区: {ws_id}")
                    return ws

            # 创建工作区
            ws = Workspace(ws_id, self.root)
            await ws.create()

            # 更新元数据
            if task_id or session_id:
                metadata = ws.get_metadata()
                if task_id:
                    metadata["task_id"] = task_id
                if session_id:
                    metadata["session_id"] = session_id
                (ws.metadata_path / "info.json").write_text(
                    json.dumps(metadata, ensure_ascii=False)
                )

            self._workspaces[ws_id] = ws

            logger.info(f"[WorkspaceManager] 创建工作区: {ws_id}")

            return ws

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """
        获取已有工作区

        Args:
            workspace_id: 工作区 ID

        Returns:
            Workspace 对象或 None
        """
        # 优先从内存缓存
        if workspace_id in self._workspaces:
            return self._workspaces[workspace_id]

        # 检查磁盘是否存在
        ws = Workspace(workspace_id, self.root)
        if ws.path.exists():
            ws._active = True
            self._workspaces[workspace_id] = ws
            return ws

        return None

    async def archive_workspace(self, workspace_id: str) -> Optional[str]:
        """
        存档并销毁工作区

        Args:
            workspace_id: 工作区 ID

        Returns:
            存档路径
        """
        async with self._lock:
            ws = await self.get_workspace(workspace_id)
            if not ws:
                logger.warning(f"[WorkspaceManager] 工作区不存在: {workspace_id}")
                return None

            archive_path = await ws.destroy(archive=True)

            if workspace_id in self._workspaces:
                del self._workspaces[workspace_id]

            return archive_path

    async def destroy_workspace(
        self,
        workspace_id: str,
        archive: bool = False
    ) -> bool:
        """
        销毁工作区

        Args:
            workspace_id: 工作区 ID
            archive: 是否先存档

        Returns:
            是否成功
        """
        async with self._lock:
            ws = await self.get_workspace(workspace_id)
            if not ws:
                return False

            await ws.destroy(archive=archive)

            if workspace_id in self._workspaces:
                del self._workspaces[workspace_id]

            return True

    async def cleanup_idle(
        self,
        max_age_hours: int = 24
    ) -> int:
        """
        清理空闲工作区

        Args:
            max_age_hours: 最大空闲小时数

        Returns:
            清理的工作区数量
        """
        if not self.root.exists():
            return 0

        cutoff = time.time() - (max_age_hours * 3600)
        cleaned = 0

        async with self._lock:
            for ws_id, ws in list(self._workspaces.items()):
                metadata = ws.get_metadata()
                created_at = metadata.get("created_at", 0)

                if created_at < cutoff:
                    await ws.destroy(archive=True)
                    del self._workspaces[ws_id]
                    cleaned += 1

            # 清理不在内存缓存中的过期工作区
            if self.root.exists():
                for item in self.root.iterdir():
                    if item.is_dir() and item.name not in self._workspaces:
                        metadata_file = item / Workspace.METADATA_DIR / "info.json"
                        if metadata_file.exists():
                            metadata = json.loads(metadata_file.read_text())
                            created_at = metadata.get("created_at", 0)
                            if created_at < cutoff:
                                shutil.rmtree(item)
                                cleaned += 1

        if cleaned > 0:
            logger.info(f"[WorkspaceManager] 清理了 {cleaned} 个空闲工作区")

        return cleaned

    async def get_workspace_stats(self) -> Dict[str, Any]:
        """获取工作区统计"""
        active_count = len(self._workspaces)
        total_size = 0

        if self.root.exists():
            for item in self.root.iterdir():
                if item.is_dir():
                    total_size += sum(
                        f.stat().st_size
                        for f in item.rglob("*")
                        if f.is_file()
                    )

        return {
            "active_workspaces": active_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2)
        }


# 全局单例
workspace_manager = WorkspaceManager()


def get_workspace_manager() -> WorkspaceManager:
    """获取工作区管理器单例"""
    return workspace_manager
