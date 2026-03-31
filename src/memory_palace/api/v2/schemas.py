"""
v2/schemas.py - API v2 schemas
"""
from pydantic import BaseModel
from typing import Optional

class MessageCreateV2(BaseModel):
    content: str
    session_id: Optional[str] = None
    user_id: str
    context: Optional[dict] = None
    priority: Optional[str] = "normal"  # low, normal, high

class AgentInvokeRequest(BaseModel):
    agent_name: str
    input_data: dict
    timeout: Optional[float] = 30.0

class BatchMessageRequest(BaseModel):
    messages: list[MessageCreateV2]
