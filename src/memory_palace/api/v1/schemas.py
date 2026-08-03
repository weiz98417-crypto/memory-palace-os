"""
v1/schemas.py - Pydantic schemas for API v1
"""
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from datetime import datetime


class MessageCreateRequest(BaseModel):
    """创建消息请求"""
    content: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    """消息响应"""
    message_id: str
    session_id: str
    content: str
    agent_name: str
    created_at: datetime
    metadata: Optional[dict] = None


class MessageAcceptedResponse(BaseModel):
    """异步消息受理响应。"""

    message_id: str
    trace_id: str
    session_id: str
    status: str = "QUEUED"
    created_at: datetime


class MessageStatusResponse(BaseModel):
    """异步消息处理状态。"""

    message_id: str
    trace_id: str
    session_id: str
    user_id: Optional[str] = None
    venue_id: str
    content: str
    status: str
    target_agent: Optional[str] = None
    reply_text: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 4
    manual_retry_count: int = 0
    retryable: bool = False
    dead_letter_id: Optional[str] = None
    delivery_status: str = "PENDING"
    delivery_error: Optional[str] = None
    delivered_at: Optional[float] = None
    created_at: float
    updated_at: float
    processed_at: Optional[float] = None


class AssistantMessageCreateRequest(BaseModel):
    channel: Literal["WEB"] = "WEB"
    content: str = Field(..., min_length=1, max_length=5000)
    external_message_id: str = Field(..., min_length=1, max_length=128)
    external_conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    metadata: Optional[dict[str, Any]] = None
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class CanonicalMessageAcceptedResponse(BaseModel):
    message_id: str
    trace_id: str
    session_id: str
    status: str
    channel: str
    external_message_id: str
    external_conversation_id: str
    duplicate: bool = False
    reply_text: Optional[str] = None
    created_at: datetime
    identity: Optional[dict[str, Any]] = None


class AssistantMessageRetryResponse(BaseModel):
    message_id: str
    trace_id: str
    session_id: str
    status: Literal["RETRYING"] = "RETRYING"
    attempt_count: int
    manual_retry_count: int
    stream_message_id: str


class SimulatorMessageCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=5000)
    external_message_id: str = Field(..., min_length=1, max_length=128)
    external_conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    metadata: Optional[dict[str, Any]] = None
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class SimulatorIdentityResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str
    venue_id: str
    organization_name: str
    venue_name: str
    department: Optional[str] = None
    job_title: Optional[str] = None
    external_tenant_id: Optional[str] = None
    external_user_id: Optional[str] = None
    wecom_binding_status: str
    status: str


class SimulatorIdentitiesResponse(BaseModel):
    identities: list[SimulatorIdentityResponse]


class SimulatorOutboxItem(BaseModel):
    id: str
    kind: Literal["CONTROLLED_ACTION", "OUTBOUND_MESSAGE"]
    session_id: str
    approval_id: Optional[str] = None
    business_id: Optional[str] = None
    supersedes_approval_id: Optional[str] = None
    supersedes_business_id: Optional[str] = None
    push_id: Optional[str] = None
    event_id: Optional[str] = None
    task_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_label: str
    message: str
    status: Literal["PENDING", "REJECTED", "EXECUTING", "SUCCEEDED", "FAILED"]
    status_summary: str
    approval_status: Optional[str] = None
    execution_status: Optional[str] = None
    delivery_status: Optional[str] = None
    review_comment: Optional[str] = None
    execution_error: Optional[str] = None
    delivery_error: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: float
    updated_at: float


class SimulatorOutboxResponse(BaseModel):
    session_id: str
    user_id: str
    items: list[SimulatorOutboxItem]


class ChannelIdentityCreateRequest(BaseModel):
    channel: Literal["WECOM_SIMULATOR"] = "WECOM_SIMULATOR"
    external_tenant_id: str = Field(..., min_length=1, max_length=128)
    external_user_id: str = Field(..., min_length=1, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=64)
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"


class ChannelIdentityResponse(BaseModel):
    id: str
    venue_id: str
    channel: str
    external_tenant_id: str
    external_user_id: str
    user_id: str
    status: str
    created_at: float
    updated_at: float


class WeComMessageCreateRequest(BaseModel):
    external_tenant_id: str = Field(..., min_length=1, max_length=128)
    external_user_id: str = Field(..., min_length=1, max_length=128)
    external_message_id: str = Field(..., min_length=1, max_length=128)
    external_conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=5000)
    metadata: Optional[dict[str, Any]] = None
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class AssistantIdentityResponse(BaseModel):
    user_id: str
    display_name: str
    role: str
    venue_id: str
    status: str


class AssistantSessionSummary(BaseModel):
    session_id: str
    user_id: str
    display_name: str
    role: str
    venue_id: str
    channel: str
    external_conversation_id: str
    stage: str
    message_count: int
    created_at: float
    updated_at: float
    last_message: Optional[str] = None
    last_status: Optional[str] = None


class AssistantSessionsResponse(BaseModel):
    sessions: list[AssistantSessionSummary]


class AssistantConversationMessage(BaseModel):
    id: str
    message_id: str
    session_id: str
    trace_id: str
    role: Literal["user", "assistant"]
    content: Optional[str] = None
    status: str
    channel: str
    created_at: float
    business_cards: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 4
    manual_retry_count: int = 0
    retryable: bool = False
    delivery_status: Optional[str] = None
    delivery_error: Optional[str] = None
    delivered_at: Optional[float] = None


class AssistantSessionMessagesResponse(BaseModel):
    session: AssistantSessionSummary
    identity: AssistantIdentityResponse
    messages: list[AssistantConversationMessage]


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
