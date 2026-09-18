"""Typed contracts for the ticket-08 scenic Agent prototype."""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(ContractModel):
    source_id: str
    title: str
    version: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"] = "SOP"


class ContextTriggerOutput(ContractModel):
    normalized_context: str
    evidence_refs: list[str] = Field(default_factory=list)


class RouterOutput(ContractModel):
    intent: str
    severity: Literal["P0", "P1", "P2", "P3", "P4"]
    risk_codes: list[str] = Field(default_factory=list)


class MemoryOpsOutput(ContractModel):
    evidence_status: Literal["GROUNDED", "NO_EVIDENCE"]
    advice: str
    citations: list[Citation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_grounding(self) -> "MemoryOpsOutput":
        if self.evidence_status == "NO_EVIDENCE":
            if "没有依据" not in self.advice:
                raise ValueError("no-evidence advice must contain 没有依据")
            if self.citations:
                raise ValueError("no-evidence advice must not contain citations")
        elif not self.citations:
            raise ValueError("grounded advice requires at least one citation")
        return self


class CommanderOutput(ContractModel):
    next_actions: list[str] = Field(default_factory=list)
    requires_human_approval: bool
    closure_summary: str

    @model_validator(mode="after")
    def validate_human_approval(self) -> "CommanderOutput":
        high_risk_markers = ("停运", "备用车", "启用备用", "解除风险")
        if any(any(marker in action for marker in high_risk_markers) for action in self.next_actions):
            if not self.requires_human_approval:
                raise ValueError("high-risk actions require human approval")
        return self


class PrototypeRequest(ContractModel):
    venue_id: str
    incident_id: str
    event_id: str
    query: str
    field_evidence: str
    incident_title: str
    priority: str
    sop_hit: dict
    mode: Literal["ADVICE"] = "ADVICE"
    attempt: int = 1
    trace_id: str = ""


class PrototypeResult(ContractModel):
    incident_id: str
    event_id: str
    trace_id: str
    context: ContextTriggerOutput
    router: RouterOutput
    memory_ops: MemoryOpsOutput
    commander: CommanderOutput
    call_record_ids: list[str]
    tei_evidence: dict


def build_call_record(
    *,
    venue_id: str,
    incident_id: str,
    mode: str,
    attempt: int,
    agent_role: str,
    agent_name: str,
    provider: str,
    model_name: str,
    request_id: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    latency_seconds: float,
    trace_id: str,
    is_mock: bool,
    created_at: float | None = None,
) -> dict:
    call_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "memory-palace-llm-call",
                    venue_id,
                    incident_id,
                    mode,
                    str(attempt),
                    agent_role,
                    "1",
                )
            ),
        )
    )
    return {
        "id": call_id,
        "venue_id": venue_id,
        "trace_id": trace_id,
        "agent_id": agent_role,
        "agent_name": agent_name,
        "provider": provider,
        "model_name": model_name,
        "status": "MOCKED" if is_mock else "SUCCEEDED",
        "attempt_count": 1,
        "latency_seconds": float(latency_seconds),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(prompt_tokens) + int(completion_tokens),
        "request_id": request_id,
        "error_type": None,
        "error_message": None,
        "is_mock": bool(is_mock),
        "created_at": float(created_at or time.time()),
    }
