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
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .business_ids import build_business_id
from .event_activities import append_event_activity


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
    venue_id: str = ""
    business_id: str = ""
    event_id: Optional[str] = None
    task_id: Optional[str] = None
    supersedes_approval_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    evidence_snapshot: Dict[str, Any] = field(default_factory=dict)
    correlation_trace_id: str = ""
    execution_trace_id: Optional[str] = None
    execution_status: str = "NOT_STARTED"
    status: str = "PENDING"  # PENDING/APPROVED/REJECTED
    reviewed_at: Optional[float] = None
    reviewed_by: Optional[str] = None
    comment: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    execution_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "venue_id": self.venue_id,
            "business_id": self.business_id,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "supersedes_approval_id": self.supersedes_approval_id,
            "idempotency_key": self.idempotency_key,
            "evidence_snapshot": self.evidence_snapshot,
            "correlation_trace_id": self.correlation_trace_id,
            "execution_trace_id": self.execution_trace_id,
            "execution_status": self.execution_status,
            "status": self.status,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "comment": self.comment,
            "execution_result": self.execution_result,
            "execution_error": self.execution_error,
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

    def __init__(self, db_client=None):
        self._tool_permissions: Dict[str, ToolPermission] = {}
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
        self._cooldown_cache: Dict[tuple[str, str], float] = {}
        # [修复] 保存通知 task 引用防止被 GC 回收
        self._db = db_client

        # 注册默认工具权限
        self._register_defaults()

    def set_database(self, db_client) -> None:
        self._db = db_client

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
            "send_in_app_alert",
            SensitivityLevel.APPROVAL,
            description="发送站内告警"
        )
        self.register_tool(
            "make_phone_call",
            SensitivityLevel.APPROVAL,
            description="发起电话呼叫"
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

        if permission.level == SensitivityLevel.APPROVAL and context.get("idempotency_key"):
            replay = await self._lookup_idempotent_approval(tool_name, args, context)
            if replay is not None:
                return replay

        # 检查冷却时间
        cooldown_key = (context.get("venue_id", ""), tool_name)
        if cooldown_key in self._cooldown_cache:
            last_exec = self._cooldown_cache[cooldown_key]
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
            return await self._execute_tool(tool_name, args, context)

        # Level 1: 记录日志后执行
        if permission.level == SensitivityLevel.LOGGED:
            await self._log_invocation(tool_name, args, context)
            return await self._execute_tool(tool_name, args, context)

        # Level 2: 需要审批
        if permission.level == SensitivityLevel.APPROVAL:
            return await self._request_approval(tool_name, args, context)

        return {
            "status": "error",
            "message": f"Unknown permission level for tool {tool_name}"
        }

    async def _execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行工具"""
        try:
            from ..tools.tool_executor import execute_tool
            result = await execute_tool(tool_name, args, context=context)
            if result.get("status") != "error":
                cooldown_key = ((context or {}).get("venue_id", ""), tool_name)
                self._cooldown_cache[cooldown_key] = time.time()
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
        if not self._db:
            return
        trace_id = str(
            context.get("execution_trace_id")
            or context.get("trace_id")
            or context.get("correlation_trace_id")
            or uuid.uuid4()
        )
        await self._db.execute(
            """
            INSERT INTO tool_invocation_logs
            (venue_id, tool_name, args, session_id, user_id, agent_name,
             logged_at, trace_id, approval_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context.get("venue_id", ""),
                tool_name,
                json.dumps(args),
                context.get("session_id", ""),
                context.get("user_id", ""),
                context.get("agent_name", "unknown"),
                time.time(),
                trace_id,
                context.get("approval_id"),
            )
        )
        logger.debug(f"[PermissionEngine] 工具调用已记录: {tool_name}")

    async def _request_approval(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建待审批请求"""
        approval_id = str(uuid.uuid4())
        requested_at = time.time()
        correlation_trace_id = str(
            context.get("correlation_trace_id")
            or context.get("trace_id")
            or uuid.uuid4()
        )
        idempotency_key = str(context.get("idempotency_key") or "").strip() or None
        evidence_snapshot = context.get("evidence_snapshot")
        if not isinstance(evidence_snapshot, dict):
            evidence_snapshot = {}

        approval = ApprovalRequest(
            approval_id=approval_id,
            tool_name=tool_name,
            args=args,
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", ""),
            requested_at=requested_at,
            requested_by=context.get("agent_name", "unknown"),
            venue_id=context.get("venue_id", ""),
            business_id=build_business_id("SP", approval_id, requested_at),
            event_id=context.get("event_id") or None,
            task_id=context.get("task_id") or None,
            supersedes_approval_id=context.get("supersedes_approval_id") or None,
            idempotency_key=idempotency_key,
            evidence_snapshot=evidence_snapshot,
            correlation_trace_id=correlation_trace_id,
        )

        inserted = await self._persist_approval(approval)
        if not inserted:
            replay = await self._lookup_idempotent_approval(tool_name, args, context)
            if replay is not None:
                return replay
            raise RuntimeError("approval persistence conflict without an idempotent match")

        self._pending_approvals[approval_id] = approval
        await self._append_approval_activity(
            approval,
            "APPROVAL_RESUBMITTED" if approval.supersedes_approval_id else "APPROVAL_REQUESTED",
            created_by=approval.user_id,
        )
        await self._notify_admin(approval)

        logger.info(
            f"[PermissionEngine] 待审批请求已创建: {tool_name}, "
            f"approval_id={approval_id}, args={args}"
        )

        return self._approval_response(approval)

    async def _lookup_idempotent_approval(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        idempotency_key = str(context.get("idempotency_key") or "").strip()
        venue_id = str(context.get("venue_id") or "")
        if not self._db or not idempotency_key:
            return None
        row = await self._db.fetch_one(
            """
            SELECT * FROM approval_requests
            WHERE venue_id = ? AND idempotency_key = ?
            """,
            (venue_id, idempotency_key),
        )
        if not row:
            return None
        if not self._approval_matches_request(row, tool_name, args, context):
            return {
                "status": "idempotency_conflict",
                "approval_id": row["approval_id"],
                "business_id": row.get("business_id") or "",
                "tool_name": row["tool_name"],
                "message": "Idempotency-Key 已用于不同的审批请求",
            }
        approval = self._approval_from_row(row)
        self._pending_approvals[approval.approval_id] = approval
        await self._append_approval_activity(
            approval,
            "APPROVAL_RESUBMITTED" if approval.supersedes_approval_id else "APPROVAL_REQUESTED",
            created_by=approval.user_id,
        )
        return self._approval_response(approval, idempotent_replay=True)

    @staticmethod
    def _approval_matches_request(
        row: Dict[str, Any],
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> bool:
        stored_args = row.get("args") or {}
        if isinstance(stored_args, str):
            try:
                stored_args = json.loads(stored_args)
            except json.JSONDecodeError:
                return False
        return (
            row.get("tool_name") == tool_name
            and stored_args == args
            and (row.get("session_id") or "") == (context.get("session_id") or "")
            and (row.get("user_id") or "") == (context.get("user_id") or "")
            and (row.get("event_id") or None) == (context.get("event_id") or None)
            and (row.get("task_id") or None) == (context.get("task_id") or None)
            and (row.get("supersedes_approval_id") or None)
            == (context.get("supersedes_approval_id") or None)
        )

    @staticmethod
    def _approval_from_row(row: Dict[str, Any]) -> ApprovalRequest:
        args = row.get("args") or {}
        if isinstance(args, str):
            args = json.loads(args)
        evidence_snapshot = row.get("evidence_snapshot_json") or {}
        if isinstance(evidence_snapshot, str):
            evidence_snapshot = json.loads(evidence_snapshot)
        execution_result = row.get("execution_result")
        if isinstance(execution_result, str):
            execution_result = json.loads(execution_result)
        return ApprovalRequest(
            approval_id=row["approval_id"],
            tool_name=row["tool_name"],
            args=args,
            session_id=row.get("session_id") or "",
            user_id=row.get("user_id") or "",
            requested_at=row["requested_at"],
            requested_by=row.get("requested_by") or "unknown",
            venue_id=row.get("venue_id") or "",
            business_id=row.get("business_id") or "",
            event_id=row.get("event_id"),
            task_id=row.get("task_id"),
            supersedes_approval_id=row.get("supersedes_approval_id"),
            idempotency_key=row.get("idempotency_key"),
            evidence_snapshot=evidence_snapshot,
            correlation_trace_id=row.get("correlation_trace_id") or "",
            execution_trace_id=row.get("execution_trace_id"),
            execution_status=row.get("execution_status") or "NOT_STARTED",
            status=row.get("status") or "PENDING",
            reviewed_at=row.get("reviewed_at"),
            reviewed_by=row.get("reviewed_by"),
            comment=row.get("comment"),
            execution_result=execution_result,
            execution_error=row.get("execution_error"),
        )

    @staticmethod
    def _approval_response(
        approval: ApprovalRequest,
        *,
        idempotent_replay: bool = False,
    ) -> Dict[str, Any]:
        return {
            "status": "pending_approval",
            "approval_status": approval.status,
            "approval_id": approval.approval_id,
            "business_id": approval.business_id,
            "event_id": approval.event_id,
            "task_id": approval.task_id,
            "supersedes_approval_id": approval.supersedes_approval_id,
            "tool_name": approval.tool_name,
            "idempotent_replay": idempotent_replay,
            "message": f"等待管理员审批: {approval.tool_name}",
        }

    async def _append_approval_activity(
        self,
        approval: ApprovalRequest,
        activity_type: str,
        *,
        created_by: Optional[str],
        trace_id: Optional[str] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._db or not approval.event_id:
            return
        task_snapshot = approval.evidence_snapshot.get("task")
        if not isinstance(task_snapshot, dict):
            task_snapshot = {}
        payload = {
            "approval_id": approval.approval_id,
            "approval_business_id": approval.business_id,
            "event_business_id": approval.evidence_snapshot.get("event_business_id"),
            "task_id": approval.task_id,
            "task_business_id": task_snapshot.get("business_id"),
            "task_title": task_snapshot.get("description"),
            "tool_name": approval.tool_name,
            "approval_status": approval.status,
            "supersedes_approval_id": approval.supersedes_approval_id,
        }
        if extra_payload:
            payload.update(extra_payload)
        await append_event_activity(
            self._db,
            venue_id=approval.venue_id,
            event_id=approval.event_id,
            activity_type=activity_type,
            created_by=created_by,
            session_id=approval.session_id,
            trace_id=trace_id or approval.correlation_trace_id,
            payload=payload,
            idempotency_key=f"approval:{approval.approval_id}:{activity_type.lower()}",
        )

    async def approve(
        self,
        approval_id: str,
        reviewer: str,
        comment: Optional[str] = None,
        venue_id: Optional[str] = None,
        trace_id: Optional[str] = None,
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
        if (
            not approval
            or approval.status != "PENDING"
            or approval.execution_status != "NOT_STARTED"
            or (venue_id and approval.venue_id != venue_id)
        ):
            logger.warning(f"[PermissionEngine] 审批单 {approval_id} 不存在或已处理")
            return False

        execution_trace_id = str(trace_id or approval.correlation_trace_id or uuid.uuid4())
        claimed = await self._claim_approval_execution(
            approval,
            reviewer=reviewer,
            comment=comment,
            execution_trace_id=execution_trace_id,
        )
        if not claimed:
            logger.warning(f"[PermissionEngine] 审批单 {approval_id} 已被其他执行者处理")
            return False

        execution_context = {
            "approval_id": approval.approval_id,
            "approval_business_id": approval.business_id,
            "session_id": approval.session_id,
            "event_id": approval.event_id,
            "task_id": approval.task_id,
            "user_id": approval.user_id,
            "venue_id": approval.venue_id,
            "agent_name": approval.requested_by,
            "correlation_trace_id": approval.correlation_trace_id,
            "execution_trace_id": execution_trace_id,
            "trace_id": execution_trace_id,
            "evidence_snapshot": approval.evidence_snapshot,
            "_database": self._db,
        }
        try:
            await self._append_approval_activity(
                approval,
                "APPROVAL_APPROVED",
                created_by=reviewer,
                trace_id=execution_trace_id,
                extra_payload={
                    "review_comment": comment,
                    "execution_status": approval.execution_status,
                },
            )
            await self._log_invocation(approval.tool_name, approval.args, execution_context)
        except asyncio.CancelledError:
            await self._finalize_cancelled_execution(approval)
            raise
        except Exception as exc:
            execution = {
                "status": "error",
                "code": "INVOCATION_LOG_FAILED",
                "message": str(exc),
            }
            await self._finalize_approval_execution(
                approval,
                execution_status="FAILED",
                execution_result=execution,
                execution_error=str(exc),
            )
            logger.error(f"[PermissionEngine] 工具调用日志记录失败: {exc}")
            return True

        try:
            execution = await self._execute_tool(
                approval.tool_name,
                approval.args,
                execution_context,
            )
        except asyncio.CancelledError:
            await self._finalize_cancelled_execution(approval)
            raise
        except Exception as exc:
            execution = {
                "status": "error",
                "code": "TOOL_EXECUTION_FAILED",
                "message": str(exc),
            }

        execution_failed = execution.get("status") == "error"
        await self._finalize_approval_execution(
            approval,
            execution_status="FAILED" if execution_failed else "SUCCEEDED",
            execution_result=execution,
            execution_error=(
                str(execution.get("message") or "工具执行失败")
                if execution_failed
                else None
            ),
        )

        logger.info(
            f"[PermissionEngine] 审批单 {approval_id} 已批准，工具 {approval.tool_name} 已执行"
        )

        return True

    async def reject(
        self,
        approval_id: str,
        reviewer: str,
        comment: Optional[str] = None,
        venue_id: Optional[str] = None,
        trace_id: Optional[str] = None,
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
        if (
            not approval
            or approval.status != "PENDING"
            or approval.execution_status != "NOT_STARTED"
            or (venue_id and approval.venue_id != venue_id)
        ):
            logger.warning(f"[PermissionEngine] 审批单 {approval_id} 不存在或已处理")
            return False

        reviewed_at = time.time()
        if self._db:
            updated = await self._db.execute(
                """
                UPDATE approval_requests
                SET status = 'REJECTED', reviewed_at = ?, reviewed_by = ?,
                    comment = ?, execution_status = 'NOT_EXECUTED'
                WHERE approval_id = ? AND venue_id = ? AND status = 'PENDING'
                  AND COALESCE(execution_status, 'NOT_STARTED') = 'NOT_STARTED'
                """,
                (
                    reviewed_at,
                    reviewer,
                    comment,
                    approval.approval_id,
                    approval.venue_id,
                ),
            )
            if updated != 1:
                logger.warning(f"[PermissionEngine] 审批单 {approval_id} 已被其他执行者处理")
                return False

        approval.status = "REJECTED"
        approval.execution_status = "NOT_EXECUTED"
        approval.reviewed_at = reviewed_at
        approval.reviewed_by = reviewer
        approval.comment = comment

        await self._append_approval_activity(
            approval,
            "APPROVAL_REJECTED",
            created_by=reviewer,
            trace_id=trace_id,
            extra_payload={"review_comment": comment},
        )

        logger.info(
            f"[PermissionEngine] 审批单 {approval_id} 已拒绝 by {reviewer}"
        )

        return True

    async def get_pending_approvals(
        self,
        session_id: Optional[str] = None,
        venue_id: Optional[str] = None,
    ) -> List[ApprovalRequest]:
        """获取待审批请求"""
        approvals = [
            a for a in self._pending_approvals.values()
            if a.status == "PENDING"
        ]

        if session_id:
            approvals = [a for a in approvals if a.session_id == session_id]
        if venue_id:
            approvals = [a for a in approvals if a.venue_id == venue_id]

        return approvals

    async def get_approval(
        self,
        approval_id: str,
        venue_id: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """获取审批单详情"""
        approval = self._pending_approvals.get(approval_id)
        if approval and venue_id and approval.venue_id != venue_id:
            return None
        return approval

    async def _notify_admin(self, approval: ApprovalRequest):
        """Expose pending approvals through the simulator-backed approval views."""

        logger.debug(
            "[PermissionEngine] 审批已进入企微模拟器/管理后台待办: approval_id={}",
            approval.approval_id,
        )

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

    async def _persist_approval(self, approval: ApprovalRequest) -> bool:
        """持久化审批请求到数据库"""
        if not self._db:
            return True
        inserted = await self._db.execute(
            """
            INSERT INTO approval_requests
            (approval_id, business_id, venue_id, tool_name, args, session_id,
             event_id, task_id, user_id, requested_at, requested_by,
             supersedes_approval_id, idempotency_key, evidence_snapshot_json,
             status, reviewed_at, reviewed_by, comment, correlation_trace_id,
             execution_trace_id, execution_status, execution_result,
             execution_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                approval.approval_id,
                approval.business_id,
                approval.venue_id,
                approval.tool_name,
                json.dumps(approval.args, ensure_ascii=False, sort_keys=True),
                approval.session_id,
                approval.event_id,
                approval.task_id,
                approval.user_id,
                approval.requested_at,
                approval.requested_by,
                approval.supersedes_approval_id,
                approval.idempotency_key,
                json.dumps(approval.evidence_snapshot, ensure_ascii=False, sort_keys=True),
                approval.status,
                approval.reviewed_at,
                approval.reviewed_by,
                approval.comment,
                approval.correlation_trace_id,
                approval.execution_trace_id,
                approval.execution_status,
                json.dumps(approval.execution_result, ensure_ascii=False) if approval.execution_result is not None else None,
                approval.execution_error,
            )
        )
        return inserted == 1

    async def _claim_approval_execution(
        self,
        approval: ApprovalRequest,
        *,
        reviewer: str,
        comment: Optional[str],
        execution_trace_id: str,
    ) -> bool:
        reviewed_at = time.time()
        if self._db:
            updated = await self._db.execute(
                """
                UPDATE approval_requests
                SET status = 'APPROVED', reviewed_at = ?, reviewed_by = ?,
                    comment = ?, execution_trace_id = ?, execution_status = 'EXECUTING',
                    execution_result = NULL, execution_error = NULL
                WHERE approval_id = ? AND venue_id = ? AND status = 'PENDING'
                  AND COALESCE(execution_status, 'NOT_STARTED') = 'NOT_STARTED'
                """,
                (
                    reviewed_at,
                    reviewer,
                    comment,
                    execution_trace_id,
                    approval.approval_id,
                    approval.venue_id,
                ),
            )
            if updated != 1:
                return False

        approval.status = "APPROVED"
        approval.reviewed_at = reviewed_at
        approval.reviewed_by = reviewer
        approval.comment = comment
        approval.execution_trace_id = execution_trace_id
        approval.execution_status = "EXECUTING"
        approval.execution_result = None
        approval.execution_error = None
        return True

    async def _finalize_approval_execution(
        self,
        approval: ApprovalRequest,
        *,
        execution_status: str,
        execution_result: Dict[str, Any],
        execution_error: Optional[str],
    ) -> None:
        if self._db:
            updated = await self._db.execute(
                """
                UPDATE approval_requests
                SET execution_status = ?, execution_result = ?, execution_error = ?
                WHERE approval_id = ? AND venue_id = ?
                  AND execution_status = 'EXECUTING' AND execution_trace_id = ?
                """,
                (
                    execution_status,
                    json.dumps(execution_result, ensure_ascii=False),
                    execution_error,
                    approval.approval_id,
                    approval.venue_id,
                    approval.execution_trace_id,
                ),
            )
            if updated != 1:
                raise RuntimeError(
                    f"approval execution finalization lost ownership: {approval.approval_id}"
                )

        approval.execution_status = execution_status
        approval.execution_result = execution_result
        approval.execution_error = execution_error
        result_value = execution_result.get("result", execution_result)
        if execution_status == "SUCCEEDED":
            if isinstance(result_value, dict):
                readable_result = next(
                    (
                        str(result_value[key])
                        for key in ("summary", "message", "detail", "status")
                        if result_value.get(key) not in (None, "")
                    ),
                    json.dumps(result_value, ensure_ascii=False, sort_keys=True),
                )
            elif result_value in (None, ""):
                readable_result = "动作已完成"
            else:
                readable_result = str(result_value)
            activity_type = "CONTROLLED_ACTION_EXECUTED"
            summary = f"受控动作执行成功：{readable_result}"
        else:
            readable_error = str(
                execution_error
                or execution_result.get("message")
                or "未返回具体错误"
            )
            activity_type = "CONTROLLED_ACTION_FAILED"
            summary = f"受控动作执行失败：{readable_error}"

        await self._append_approval_activity(
            approval,
            activity_type,
            created_by=approval.reviewed_by,
            trace_id=approval.execution_trace_id,
            extra_payload={
                "execution_status": execution_status,
                "execution_result": execution_result,
                "execution_error": execution_error,
                "summary": summary,
            },
        )

    async def _finalize_cancelled_execution(self, approval: ApprovalRequest) -> None:
        message = "Approval execution cancelled before completion"
        await asyncio.shield(
            self._finalize_approval_execution(
                approval,
                execution_status="FAILED",
                execution_result={
                    "status": "error",
                    "code": "EXECUTION_CANCELLED",
                    "message": message,
                },
                execution_error=message,
            )
        )

    async def reload_from_db(self):
        """从数据库加载待审批请求（启动时调用）"""
        if not self._db:
            return
        try:
            interrupted_result = json.dumps(
                {
                    "status": "error",
                    "code": "EXECUTION_INTERRUPTED",
                    "message": "Approval execution interrupted by process restart",
                },
                ensure_ascii=False,
            )
            await self._db.execute(
                """
                UPDATE approval_requests
                SET execution_status = 'FAILED',
                    execution_result = COALESCE(execution_result, ?),
                    execution_error = COALESCE(
                        execution_error,
                        'Approval execution interrupted by process restart'
                    )
                WHERE execution_status = 'EXECUTING'
                """,
                (interrupted_result,),
            )
            legacy_result = json.dumps(
                {
                    "status": "error",
                    "code": "LEGACY_EXECUTION_RESULT_MISSING",
                    "message": "Approved action has no persisted execution result",
                },
                ensure_ascii=False,
            )
            await self._db.execute(
                """
                UPDATE approval_requests
                SET execution_status = 'FAILED', execution_result = ?,
                    execution_error = COALESCE(
                        execution_error,
                        'Approved action has no persisted execution result'
                    )
                WHERE status = 'APPROVED' AND execution_result IS NULL
                  AND COALESCE(execution_status, 'NOT_STARTED') = 'NOT_STARTED'
                """,
                (legacy_result,),
            )
            rows = await self._db.fetch_all(
                "SELECT * FROM approval_requests WHERE status = ?",
                ("PENDING",)
            )
            for approval_id, approval in list(self._pending_approvals.items()):
                if approval.status == "PENDING":
                    del self._pending_approvals[approval_id]
            for row in rows:
                approval = self._approval_from_row(row)
                self._pending_approvals[approval.approval_id] = approval

            if self._pending_approvals:
                logger.info(
                    f"[PermissionEngine] 从数据库加载了 {len(self._pending_approvals)} 个待审批请求"
                )
        except Exception as e:
            logger.error(f"[PermissionEngine] 从数据库加载待审批请求失败: {e}")
            raise


# 全局单例
import asyncio
permission_engine = PermissionEngine()


def get_permission_engine() -> PermissionEngine:
    """获取权限引擎单例"""
    return permission_engine
