"""
v1/schemas.py - Pydantic schemas for API v1
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class MessageCreateRequest(BaseModel):
    """创建消息请求"""
    content: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = None
    user_id: str
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    """消息响应"""
    message_id: str
    session_id: str
    content: str
    agent_name: str
    created_at: datetime
    metadata: Optional[dict] = None


class SkillInfo(BaseModel):
    """技能信息"""
    name: str
    description: str
    version: str
    tags: list[str]


class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    user_id: str
    stage: str = ""
    active_agent: Optional[str] = ""
    current_intent: Optional[str] = ""
    current_severity: Optional[str] = ""
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    history_summary: str = ""

    # 兼容别名
    agent_name: Optional[str] = None
    message_count: int = 0
    status: str = "active"

    class Config:
        extra = "ignore"


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    timestamp: datetime
    version: str
    uptime_seconds: float
    components: dict[str, str]


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime
