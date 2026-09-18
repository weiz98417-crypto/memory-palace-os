"""Contracts for the memory_ops agent."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ...agent_contracts.models import (
    ContractModel,
    FieldEvidence,
    IncidentSnapshot,
    VerifiedKnowledge,
)
from ..context_trigger.contracts import ContextTriggerOutput
from ..router.contracts import RouterOutput

NO_EVIDENCE_TEXT = "\u6ca1\u6709\u4f9d\u636e"
RETRIEVAL_FAILED_TEXT = "\u672a\u83b7\u5f97\u6a21\u578b\u5efa\u8bae"


class KnowledgeCitation(ContractModel):
    source_id: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"]
    title: str
    version: str
    vector_score: float = Field(ge=0.0, le=1.0)
    rerank_score: float | None = None
    excerpt: str = ""


class MemoryOpsInput(ContractModel):
    incident: IncidentSnapshot
    context: ContextTriggerOutput
    routing: RouterOutput
    knowledge: VerifiedKnowledge
    field_evidence: list[FieldEvidence] = Field(default_factory=list)


class MemoryOpsOutput(ContractModel):
    evidence_status: Literal["GROUNDED", "NO_EVIDENCE", "RETRIEVAL_FAILED"]
    advice_text: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    absence_reason: str | None = None

    @model_validator(mode="after")
    def enforce_grounding(self) -> "MemoryOpsOutput":
        if self.evidence_status == "GROUNDED" and not self.citations:
            raise ValueError("grounded advice requires at least one citation")
        if self.evidence_status != "GROUNDED" and self.citations:
            raise ValueError("non-grounded output cannot cite knowledge")
        if self.evidence_status == "NO_EVIDENCE" and self.advice_text != NO_EVIDENCE_TEXT:
            raise ValueError("no evidence must say \u6ca1\u6709\u4f9d\u636e")
        if (
            self.evidence_status == "RETRIEVAL_FAILED"
            and self.advice_text != RETRIEVAL_FAILED_TEXT
        ):
            raise ValueError(
                "retrieval failure must say \u672a\u83b7\u5f97\u6a21\u578b\u5efa\u8bae"
            )
        return self


__all__ = [
    "KnowledgeCitation",
    "MemoryOpsInput",
    "MemoryOpsOutput",
    "NO_EVIDENCE_TEXT",
    "RETRIEVAL_FAILED_TEXT",
]
