"""
权限引擎 (Permissions Engine)

核心职责:
1. 定义工具敏感级别 (Level 0/1/2)
2. 在工具调用前插入权限检查 Hook
3. Level 2 工具需要人工审批后才能执行
4. 通过微信通知管理员待审批操作

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class SensitivityLevel(IntEnum):
    """工具敏感级别"""
    FREE = 0       # 直接执行，无限制
    LOGGED = 1     # 执行 + 审计日志
    APPROVAL = 2   # 需要人工审批


@dataclass
class ToolPermission:
    """工具权限配置"""
    tool_name: str
    level: SensitivityLevel
    description: str = ""
    notify_roles: List[str] = field(default_factory=lambda: ["admin"])
    cooldown_seconds: int = 60  # 同一工具最小调用间隔


@dataclass
class ApprovalRequest:
    """待审批请求"""
    approval_id: str
    tool_name: str
    args: Dict[str, Any]
    session_id: str
    user_id: str
    requested_at: float
    requested_by: str  # Agent 名称
    status: str = "PENDING"  # PENDING/APPROVED/REJECTED
    reviewed_at: Optional[float] = None
    reviewed_by: Optional[str] = None
    comment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "status": self.status,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "comment": self.comment
        }


class PermissionEngine:
    """
    权限引擎核心类

    使用示例:
        engine = PermissionEngine()
        engine.register_tool("send_sms", SensitivityLevel.APPROVAL)

        # 在 LLM 工具调用时:
        result = await engine.check_and_execute("send_sms", args, context)
        if result["status"] == "pending_approval":
            # 等待审批...
    """

    def __init__(self):
        self._tool_permissions: Dict[str, ToolPermission] = {}
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
        self._cooldown_cache: Dict[str, float] = {}
        # [修复] 保存通知 task 引用防止被 GC 回收
        self._pending_notifications: List[asyncio.Task] = []

        # 注册默认工具权限
        self._register_defaults()

    def _register_defaults(self):
        """注册默认工具权限"""
        # Level 0: 直接执行
        self.register_tool(
            "search_memory",
            SensitivityLevel.FREE,
            description="查询向量内存"
        )
        self.register_tool(
            "get_context",
            SensitivityLevel.FREE,
            description="获取会话上下文"
        )

        # Level 1: 记录日志
        self.register_tool(
            "write_memory",
            SensitivityLevel.LOGGED,
            description="写入向量内存"
        )
        self.register_tool(
            "update_session",
            SensitivityLevel.LOGGED,
            description="更新会话状态"
        )

        # Level 2: 需要审批
        self.register_tool(
            "send_sms",
            SensitivityLevel.APPROVAL,
            description="发送短信"
        )
        self.register_tool(
            "send_alert",
            SensitivityLevel.APPROVAL,
            description="发送告警通知"
        )
        self.register_tool(
            "make_phone_call",
            SensitivityLevel.APPROVAL,
            description="发起电话呼叫"
        )
        self.register_tool(
            "send_wechat_message",
            SensitivityLevel.APPROVAL,
            description="发送微信消息"
        )

        logger.info("[PermissionEngine] 默认工具权限注册完成")

    def register_tool(
        self,
        tool_name: str,
        level: SensitivityLevel,
        description: str = "",
        **kwargs
    ):
        """注册工具权限"""
        self._tool_permissions[tool_name] = ToolPermission(
            tool_name=tool_name,
            level=level,
            description=description,
            **kwargs
        )
        logger.debug(f"[PermissionEngine] 注册工具权限: {tool_name} -> Level {level.value}")

    def get_tool_permission(self, tool_name: str) -> Optional[ToolPermission]:
        """获取工具权限配置"""
        return self._tool_permissions.get(tool_name)

    async def check_and_execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查权限并执行工具

        Args:
            tool_name: 工具名称
            args: 工具参数
            context: 执行上下文 (session_id, user_id, agent_name 等)

        Returns:
            {
                "status": "executed", "result": ...           # Level 0/1 执行成功
                "status": "pending_approval", "approval_id": ... # Level 2 等待审批
                "status": "cooldown", "retry_after": ...       # 冷却中
                "status": "rejected", "reason": ...             # 被拒绝
            }
        """
        permission = self._tool_permissions.get(tool_name)
        if not permission:
            # 未知工具默认为 Level 2 (需要审批)
            permission = ToolPermission(tool_name, SensitivityLevel.APPROVAL)
            self._tool_permissions[tool_name] = permission
            logger.warning(f"[PermissionEngine] 未知工具 {tool_name}，默认设置为需要审批")

        # 检查冷却时间
        if tool_name in self._cooldown_cache:
            last_exec = self._cooldown_cache[tool_name]
            if time.time() - last_exec < permission.cooldown_seconds:
                retry_after = permission.cooldown_seconds - (time.time() - last_exec)
                logger.warning(
                    f"[PermissionEngine] 工具 {tool_name} 冷却中，"
                    f"{retry_after:.1f}秒后可重试"
                )
                return {
                    "status": "cooldown",
                    "retry_after": retry_after,
                    "tool_name": tool_name
                }

        # Level 0: 直接执行
        if permission.level == SensitivityLevel.FREE:
            return await self._execute_tool(tool_name, args)

        # Level 1: 记录日志后执行
        if permission.level == SensitivityLevel.LOGGED:
            await self._log_invocation(tool_name, args, context)
            return await self._execute_tool(tool_name, args)

        # Level 2: 需要审批
        if permission.level == SensitivityLevel.APPROVAL:
            return await self._request_approval(tool_name, args, context)

        return {
            "status": "error",
            "message": f"Unknown permission level for tool {tool_name}"
        }

    async def _execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具"""
        try:
            from ..tools.tool_executor import execute_tool
            result = await execute_tool(tool_name, args)
            self._cooldown_cache[tool_name] = time.time()
            return result
        except Exception as e:
            logger.error(f"[PermissionEngine] 工具 {tool_name} 执行失败: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    async def _log_invocation(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any]
    ):
        """记录工具调用日志 (Level 1)"""
        try:
            from ..knowledge.db_client import db_client
            if db_client:
                await db_client.execute(
                    """
                    INSERT INTO tool_invocation_logs
                    (tool_name, args, session_id, user_id, agent_name, logged_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_name,
                        json.dumps(args),
                        context.get("session_id", ""),
                        context.get("user_id", ""),
                        context.get("agent_name", "unknown"),
                        time.time()
                    )
                )
                logger.debug(f"[PermissionEngine] 工具调用已记录: {tool_name}")
        except Exception as e:
            logger.error(f"[PermissionEngine] 工具调用日志记录失败: {e}")

    async def _request_approval(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建待审批请求"""
        approval_id = str(uuid.uuid4())

        approval = ApprovalRequest(
            approval_id=approval_id,
            tool_name=tool_name,
            args=args,
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", ""),
            requested_at=time.time(),
            requested_by=context.get("agent_name", "unknown")
        )

        # 存储到内存
        self._pending_approvals[approval_id] = approval

        # 持久化到数据库
        await self._persist_approval(approval)

        # 发送微信通知给管理员
        await self._notify_admin(approval)

        logger.info(
            f"[PermissionEngine] 待审批请求已创建: {tool_name}, "
            f"approval_id={approval_id}, args={args}"
        )

        return {
            "status": "pending_approval",
            "approval_id": approval_id,
            "tool_name": tool_name,
            "message": f"等待管理员审批: {tool_name}"
        }

    async def approve(
        self,
        approval_id: str,
        reviewer: str,
        comment: Optional[str] = None
    ) -> bool:
        """
        审批通过

        Args:
            approval_id: 审批单 ID
            reviewer: 审批人
            comment: 审批意见

        Returns:
            是否成功
        """
        approval = self._pending_approvals.get(approval_id)
        if not approval or approval.status != "PENDING":
            logger.warning(f"[PermissionEngine] 审批单 {approval_id} 不存在或已处理")
            return False

        # 更新状态
        approval.status = "APPROVED"
        approval.reviewed_at = time.time()
        approval.reviewed_by = reviewer
        approval.comment = comment

        await self._update_approval_status(approval)

        # 执行工具
        await self._execute_tool(approval.tool_name, approval.args)

        # 更新冷却时间
        self._cooldown_cache[approval.tool_name] = time.time()

        logger.info(
            f"[PermissionEngine] 审批单 {approval_id} 已批准，工具 {approval.tool_name} 已执行"
        )

        return True

    async def reject(
        self,
        approval_id: str,
        reviewer: str,
        comment: Optional[str] = None
    ) -> bool:
        """
        审批拒绝

        Args:
            approval_id: 审批单 ID
            reviewer: 审批人
            comment: 拒绝原因

        Returns:
            是否成功
        """
        approval = self._pending_approvals.get(approval_id)
        if not approval or approval.status != "PENDING":
            logger.warning(f"[PermissionEngine] 审批单 {approval_id} 不存在或已处理")
            return False

        approval.status = "REJECTED"
        approval.reviewed_at = time.time()
        approval.reviewed_by = reviewer
        approval.comment = comment

        await self._update_approval_status(approval)

        logger.info(
            f"[PermissionEngine] 审批单 {approval_id} 已拒绝 by {reviewer}"
        )

        return True

    async def get_pending_approvals(
        self,
        session_id: Optional[str] = None
    ) -> List[ApprovalRequest]:
        """获取待审批请求"""
        approvals = [
            a for a in self._pending_approvals.values()
            if a.status == "PENDING"
        ]

        if session_id:
            approvals = [a for a in approvals if a.session_id == session_id]

        return approvals

    async def get_approval(self, approval_id: str) -> Optional[ApprovalRequest]:
        """获取审批单详情"""
        return self._pending_approvals.get(approval_id)

    async def _notify_admin(self, approval: ApprovalRequest):
        """发送微信通知给管理员"""
        try:
            admin_user = os.environ.get("ADMIN_USER_ID", "admin")
            message = self._format_approval_message(approval)

            from ..tools.wechat_client import get_wechat_client

            # [修复] 保存 task 引用防止被 GC 回收
            task = asyncio.create_task(
                get_wechat_client().send_text(admin_user, message)
            )
            self._pending_notifications.append(task)
            task.add_done_callback(
                lambda t: self._pending_notifications.remove(t)
                if t in self._pending_notifications else None
            )

            logger.debug(f"[PermissionEngine] 管理员通知已发送: {admin_user}")

        except Exception as e:
            logger.error(f"[PermissionEngine] 发送管理员通知失败: {e}")

    def _format_approval_message(self, approval: ApprovalRequest) -> str:
        """格式化审批通知消息"""
        time_str = datetime.fromtimestamp(approval.requested_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # 敏感信息脱敏
        safe_args = self._mask_sensitive_args(approval.args)

        message = (
            f"【待审批操作】\n"
            f"工具: {approval.tool_name}\n"
            f"申请人: {approval.requested_by}\n"
            f"会话: {approval.session_id}\n"
            f"时间: {time_str}\n"
            f"参数: {json.dumps(safe_args, ensure_ascii=False)}\n"
            f"审批ID: {approval.approval_id}\n\n"
            f"回复 APPROVE#{approval.approval_id} 批准\n"
            f"回复 REJECT#{approval.approval_id} 拒绝"
        )

        return message

    def _mask_sensitive_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏敏感参数"""
        sensitive_keys = ["password", "token", "api_key", "secret", "phone", "id_card"]
        masked = args.copy()

        for key in masked:
            if any(s in key.lower() for s in sensitive_keys):
                masked[key] = "***"
            elif isinstance(masked[key], str) and len(masked[key]) > 8:
                # 手机号等长字符串部分隐藏
                masked[key] = masked[key][:3] + "***" + masked[key][-3:]

        return masked

    async def _persist_approval(self, approval: ApprovalRequest):
        """持久化审批请求到数据库"""
        try:
            from ..knowledge.db_client import db_client
            if db_client:
                await db_client.execute(
                    """
                    INSERT OR REPLACE INTO approval_requests
                    (approval_id, tool_name, args, session_id, user_id,
                     requested_at, requested_by, status, reviewed_at,
                     reviewed_by, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval.approval_id,
                        approval.tool_name,
                        json.dumps(approval.args),
                        approval.session_id,
                        approval.user_id,
                        approval.requested_at,
                        approval.requested_by,
                        approval.status,
                        approval.reviewed_at,
                        approval.reviewed_by,
                        approval.comment
                    )
                )
        except Exception as e:
            logger.error(f"[PermissionEngine] 审批请求持久化失败: {e}")

    async def _update_approval_status(self, approval: ApprovalRequest):
        """更新审批状态到数据库"""
        try:
            from ..knowledge.db_client import db_client
            if db_client:
                await db_client.execute(
                    """
                    UPDATE approval_requests
                    SET status = ?, reviewed_at = ?, reviewed_by = ?, comment = ?
                    WHERE approval_id = ?
                    """,
                    (
                        approval.status,
                        approval.reviewed_at,
                        approval.reviewed_by,
                        approval.comment,
                        approval.approval_id
                    )
                )
        except Exception as e:
            logger.error(f"[PermissionEngine] 审批状态更新失败: {e}")

    async def reload_from_db(self):
        """从数据库加载待审批请求（启动时调用）"""
        try:
            from ..knowledge.db_client import db_client
            if not db_client:
                return

            rows = await db_client.fetch_all(
                "SELECT * FROM approval_requests WHERE status = ?",
                ("PENDING",)
            )
            for row in rows:
                approval = ApprovalRequest(
                    approval_id=row["approval_id"],
                    tool_name=row["tool_name"],
                    args=json.loads(row["args"]) if isinstance(row["args"], str) else row["args"],
                    session_id=row.get("session_id"),
                    user_id=row.get("user_id"),
                    requested_at=row["requested_at"],
                    requested_by=row.get("requested_by"),
                    status=row.get("status", "PENDING"),
                )
                self._pending_approvals[approval.approval_id] = approval

            if self._pending_approvals:
                logger.info(
                    f"[PermissionEngine] 从数据库加载了 {len(self._pending_approvals)} 个待审批请求"
                )
        except Exception as e:
            logger.warning(f"[PermissionEngine] 从数据库加载待审批请求失败（不影响启动）: {e}")


# 全局单例
import asyncio
permission_engine = PermissionEngine()


def get_permission_engine() -> PermissionEngine:
    """获取权限引擎单例"""
    return permission_engine
