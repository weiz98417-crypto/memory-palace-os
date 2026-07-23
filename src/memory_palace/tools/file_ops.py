"""
安全文件操作 (Safe File Operations)

核心职责:
1. 封装文件读写操作，自动限制在工作区内
2. 防止路径遍历攻击
3. 提供异步文件操作接口

所有文件操作必须通过本模块，不允许直接使用 open()/Path 操作

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

# 尝试导入 aiofiles (异步文件操作)
try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False
    logger.warning("aiofiles 未安装，文件操作将使用同步模式")


class SafeFileOps:
    """
    安全文件操作类

    所有路径操作都在指定的工作区内进行，路径遍历攻击会抛出异常。

    使用示例:
        ops = SafeFileOps(workspace_id="task-123")
        content = await ops.read("input/data.txt")
        await ops.write("output/result.txt", "Hello")
    """

    def __init__(self, workspace_id: str):
        from ..core.workspace import workspace_manager

        self.workspace_id = workspace_id
        self._workspace = None
        self._workspace_manager = workspace_manager

    async def _get_workspace(self):
        """懒加载工作区"""
        if self._workspace is None:
            self._workspace = await self._workspace_manager.get_workspace(
                self.workspace_id
            )
        return self._workspace

    def _validate_path(self, relative_path: str) -> Path:
        """
        验证相对路径不包含路径遍历攻击

        Args:
            relative_path: 相对路径

        Returns:
            解析后的 Path

        Raises:
            ValueError: 如果路径包含遍历攻击
        """
        # 规范化路径
        path = Path(relative_path)

        # 检查是否包含绝对路径
        if path.is_absolute():
            raise ValueError(f"禁止使用绝对路径: {relative_path}")

        # 检查路径遍历攻击
        if ".." in relative_path or relative_path.startswith("/"):
            raise ValueError(f"路径遍历攻击检测: {relative_path}")

        # 检查 Windows 路径遍历
        if "\\" in relative_path:
            parts = relative_path.replace("\\", "/").split("/")
            if ".." in parts:
                raise ValueError(f"路径遍历攻击检测: {relative_path}")

        return path

    async def read(self, relative_path: str) -> str:
        """
        读取文件

        Args:
            relative_path: 相对路径 (相对于工作区)

        Returns:
            文件内容

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 路径遍历攻击
        """
        ws = await self._get_workspace()
        if not ws:
            raise ValueError(f"工作区 {self.workspace_id} 不存在")

        path = ws.get_output_path(self._validate_path(relative_path))

        if HAS_AIOFILES:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                return await f.read()
        else:
            return path.read_text(encoding="utf-8")

    async def write(
        self,
        relative_path: str,
        content: str,
        encoding: str = "utf-8"
    ) -> bool:
        """
        写入文件

        Args:
            relative_path: 相对路径
            content: 文件内容
            encoding: 编码

        Returns:
            是否成功

        Raises:
            ValueError: 路径遍历攻击
        """
        ws = await self._get_workspace()
        if not ws:
            raise ValueError(f"工作区 {self.workspace_id} 不存在")

        path = ws.get_output_path(self._validate_path(relative_path))

        # 确保父目录存在
        path.parent.mkdir(parents=True, exist_ok=True)

        if HAS_AIOFILES:
            async with aiofiles.open(path, "w", encoding=encoding) as f:
                await f.write(content)
        else:
            path.write_text(content, encoding=encoding)

        logger.debug(f"[SafeFileOps] 写入文件: {self.workspace_id}/{relative_path}")

        return True

    async def append(
        self,
        relative_path: str,
        content: str,
        encoding: str = "utf-8"
    ) -> bool:
        """
        追加写入

        Args:
            relative_path: 相对路径
            content: 追加内容
            encoding: 编码

        Returns:
            是否成功
        """
        ws = await self._get_workspace()
        if not ws:
            raise ValueError(f"工作区 {self.workspace_id} 不存在")

        path = ws.get_output_path(self._validate_path(relative_path))

        if HAS_AIOFILES:
            async with aiofiles.open(path, "a", encoding=encoding) as f:
                await f.write(content)
        else:
            path.write_text(content, encoding=encoding, append=True)

        return True

    async def exists(self, relative_path: str) -> bool:
        """检查文件是否存在"""
        ws = await self._get_workspace()
        if not ws:
            return False

        try:
            path = ws.get_output_path(self._validate_path(relative_path))
            return path.exists()
        except ValueError:
            return False

    async def list_dir(
        self,
        relative_path: str = "."
    ) -> List[str]:
        """
        列出目录内容

        Args:
            relative_path: 相对路径

        Returns:
            文件/目录名列表
        """
        ws = await self._get_workspace()
        if not ws:
            return []

        path = ws.path / self._validate_path(relative_path)

        if not path.exists() or not path.is_dir():
            return []

        return [item.name for item in path.iterdir()]

    async def delete(self, relative_path: str) -> bool:
        """
        删除文件

        Args:
            relative_path: 相对路径

        Returns:
            是否成功
        """
        ws = await self._get_workspace()
        if not ws:
            return False

        path = ws.get_output_path(self._validate_path(relative_path))

        if path.exists():
            path.unlink()
            logger.debug(f"[SafeFileOps] 删除文件: {self.workspace_id}/{relative_path}")
            return True

        return False

    async def get_size(self, relative_path: str) -> int:
        """
        获取文件大小

        Args:
            relative_path: 相对路径

        Returns:
            文件大小 (字节)
        """
        ws = await self._get_workspace()
        if not ws:
            return 0

        path = ws.get_output_path(self._validate_path(relative_path))

        if path.exists():
            return path.stat().st_size

        return 0


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_workspace_file_ops(workspace_id: str) -> SafeFileOps:
    """
    获取指定工作区的安全文件操作实例

    Args:
        workspace_id: 工作区 ID

    Returns:
        SafeFileOps 实例
    """
    return SafeFileOps(workspace_id)


# ---------------------------------------------------------------------------
# 路径遍历黑名单 (示例)
# ---------------------------------------------------------------------------

_PATH_TRAVERSAL_PATTERNS = [
    "../",
    "..\\",
    "%2e%2e/",
    "%2e%2e\\",
    "....//",
    "....\\/",
]


def is_path_traversal(relative_path: str) -> bool:
    """
    检查是否存在路径遍历攻击

    Args:
        relative_path: 相对路径

    Returns:
        是否存在路径遍历
    """
    normalized = relative_path.lower().replace("\\", "/")

    for pattern in _PATH_TRAVERSAL_PATTERNS:
        if pattern in normalized:
            return True

    return False
