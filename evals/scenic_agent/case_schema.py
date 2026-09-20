"""Stable, versioned evaluation case schema and legacy adapters."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

Artifact = Literal["ADVICE", "DISPATCH_DRAFT", "CLOSURE_SUMMARY"]
ExpectedOutcome = Literal["READY", "FAILED", "DEGRADED"]
EvidenceStatus = Literal["GROUNDED", "NO_EVIDENCE", "RETRIEVAL_FAILED"]
CaseSource = Literal["production", "expert", "adversarial", "failure_replay"]
Severity = Literal["P0", "P1", "P2", "P3", "P4"]
RetrievalStatus = Literal["HITS", "ZERO_HITS", "RETRIEVAL_FAILED"]
FastCategory = Literal[
    "GROUNDED_ADVICE",
    "NO_EVIDENCE",
    "RETRIEVAL_SHAPE",
    "DISPATCH_DRAFT",
    "CLOSURE_SUMMARY",
    "HITL_GATES",
    "DEGRADATION_FAILURE",
    "SECURITY_TENANT",
    "ROUTER_RISK",
    "MULTI_AGENT_TRAJECTORY",
]

NO_EVIDENCE_TEXT = "没有依据"

ALLOWED_ACTIONS = frozenset(
    {
        "ADOPT",
        "IGNORE",
        "PROCEED_WITHOUT_WAITING",
        "CREATE_REPAIR_TASK",
        "CREATE_DIVERSION_TASK",
        "REQUEST_APPROVAL",
        "NO_AUTO_DISPATCH",
        "REVIEW_CLOSURE",
        "REVIEW_UNRESOLVED_RISK",
        "WAIT_ALERT_RECOVERY",
    }
)
ALLOWED_TOOLS = frozenset(
    {"send_in_app_alert", "make_phone_call", "send_sms", "search_memory"}
)
ALLOWED_MODEL_CALLS = frozenset(
    {"context_trigger", "router", "memory_ops", "commander"}
)
ALLOWED_DEGRADATIONS = frozenset(
    {
        "DISABLED",
        "TIMEOUT",
        "FAILED",
        "INVALID_OUTPUT",
        "CIRCUIT_OPEN",
        "QUOTA_EXCEEDED",
        "RETRIEVAL_FAILED",
        "USAGE_NOT_REPORTED",
    }
)
ALLOWED_SSE_EVENTS = frozenset(
    {
        "ADVICE_PENDING",
        "ADVICE_READY",
        "ADVICE_FAILED",
        "DISPATCH_DRAFT_PENDING",
        "DISPATCH_DRAFT_READY",
        "DISPATCH_DRAFT_FAILED",
        "CLOSURE_SUMMARY_PENDING",
        "CLOSURE_SUMMARY_READY",
        "CLOSURE_SUMMARY_FAILED",
    }
)


class CaseSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeHitFixture(CaseSchemaModel):
    source_id: str
    source_type: Literal["SOP", "CASE", "EXPERIENCE_CARD"]
    title: str
    version: str
    excerpt: str = ""


class FastGoldenCase(CaseSchemaModel):
    id: str
    fixture_only: Literal[True] = True
    dataset_version: str
    source: CaseSource
    category: FastCategory
    artifact: Artifact
    query: str
    retrieval_status: RetrievalStatus
    incident_context: dict[str, Any]
    knowledge_hits: list[KnowledgeHitFixture] = Field(default_factory=list)
    expected_outcome: ExpectedOutcome
    evidence_status: EvidenceStatus
    must_cite_source_ids: list[str] = Field(default_factory=list)
    forbidden_source_ids: list[str] = Field(default_factory=list)
    required_substrings: list[str] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    expected_risk: Severity
    requires_human_approval: bool
    required_tools: list[str] = Field(default_factory=list)
    expected_actions: list[str] = Field(default_factory=list)
    expected_model_calls: list[str] = Field(default_factory=list)
    allowed_degradations: list[str] = Field(default_factory=list)
    expected_sse_events: list[str] = Field(default_factory=list)
    failure_mode: str

    @model_validator(mode="after")
    def validate_case_contract(self) -> "FastGoldenCase":
        if not self.id.strip():
            raise ValueError("id must not be empty")
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if not self.failure_mode.strip():
            raise ValueError("failure_mode must not be empty")
        if not self.expected_model_calls:
            raise ValueError("expected_model_calls must not be empty")
        if not self.expected_sse_events:
            raise ValueError("expected_sse_events must not be empty")
        if not self.expected_actions:
            raise ValueError("expected_actions must not be empty")

        unknown_actions = sorted(set(self.expected_actions) - ALLOWED_ACTIONS)
        if unknown_actions:
            raise ValueError(f"unsupported expected action(s): {', '.join(unknown_actions)}")
        unknown_tools = sorted(set(self.required_tools) - ALLOWED_TOOLS)
        if unknown_tools:
            raise ValueError(f"unsupported required tool(s): {', '.join(unknown_tools)}")
        unknown_calls = sorted(set(self.expected_model_calls) - ALLOWED_MODEL_CALLS)
        if unknown_calls:
            raise ValueError(f"unsupported expected model call(s): {', '.join(unknown_calls)}")
        unknown_degradations = sorted(
            set(self.allowed_degradations) - ALLOWED_DEGRADATIONS
        )
        if unknown_degradations:
            raise ValueError(
                f"unsupported degradation(s): {', '.join(unknown_degradations)}"
            )
        unknown_events = sorted(set(self.expected_sse_events) - ALLOWED_SSE_EVENTS)
        if unknown_events:
            raise ValueError(f"unsupported SSE event(s): {', '.join(unknown_events)}")

        terminal_event = self.expected_sse_events[-1]
        if self.expected_outcome == "READY" and not terminal_event.endswith("_READY"):
            raise ValueError("READY cases must end with a *_READY SSE event")
        if self.expected_outcome == "FAILED" and not terminal_event.endswith("_FAILED"):
            raise ValueError("FAILED cases must end with a *_FAILED SSE event")
        if self.expected_outcome == "DEGRADED" and not terminal_event.endswith(
            ("_READY", "_FAILED")
        ):
            raise ValueError("DEGRADED cases must end with a terminal SSE event")
        if self.expected_outcome in {"FAILED", "DEGRADED"} and not self.allowed_degradations:
            raise ValueError(
                "FAILED/DEGRADED cases must declare allowed_degradations"
            )
        if self.category == "HITL_GATES" and not self.requires_human_approval:
            raise ValueError("HITL_GATES cases must require a human gate")
        if (
            self.artifact == "DISPATCH_DRAFT"
            and self.requires_human_approval
            and not {"CREATE_REPAIR_TASK", "REQUEST_APPROVAL"}.intersection(
                self.expected_actions
            )
        ):
            raise ValueError(
                "human-approved dispatch drafts require an approval-bearing action"
            )

        hit_ids = [hit.source_id for hit in self.knowledge_hits]
        if len(hit_ids) != len(set(hit_ids)):
            raise ValueError("knowledge_hits contains duplicate source_id values")
        if set(self.must_cite_source_ids) - set(hit_ids):
            raise ValueError("must_cite_source_ids contains a source absent from knowledge_hits")

        if self.evidence_status == "GROUNDED":
            if self.retrieval_status != "HITS":
                raise ValueError("GROUNDED cases require retrieval_status=HITS")
            if not self.must_cite_source_ids:
                raise ValueError("GROUNDED cases require at least one expected citation")
        elif self.evidence_status == "NO_EVIDENCE":
            if self.retrieval_status != "ZERO_HITS":
                raise ValueError("NO_EVIDENCE cases require retrieval_status=ZERO_HITS")
            if self.must_cite_source_ids:
                raise ValueError("NO_EVIDENCE cases cannot require citations")
            if NO_EVIDENCE_TEXT not in self.required_substrings:
                raise ValueError("NO_EVIDENCE cases must require 没有依据")
        else:
            if self.retrieval_status != "RETRIEVAL_FAILED":
                raise ValueError("RETRIEVAL_FAILED cases require retrieval_status=RETRIEVAL_FAILED")
            if self.must_cite_source_ids:
                raise ValueError("RETRIEVAL_FAILED cases cannot require citations")

        if self.artifact == "DISPATCH_DRAFT" and not any(
            event.startswith("DISPATCH_DRAFT_") for event in self.expected_sse_events
        ):
            raise ValueError("DISPATCH_DRAFT cases require DISPATCH_DRAFT_* SSE events")
        if self.artifact == "CLOSURE_SUMMARY" and not any(
            event.startswith("CLOSURE_SUMMARY_") for event in self.expected_sse_events
        ):
            raise ValueError("CLOSURE_SUMMARY cases require CLOSURE_SUMMARY_* SSE events")
        if self.artifact == "ADVICE" and not any(
            event.startswith("ADVICE_") for event in self.expected_sse_events
        ):
            raise ValueError("ADVICE cases require ADVICE_* SSE events")
        return self


class FastGoldenFixture(CaseSchemaModel):
    schema_version: Literal[2]
    fixture_only: Literal[True]
    dataset_version: str
    generated_for: str
    cases: list[FastGoldenCase]

    @model_validator(mode="after")
    def validate_fixture(self) -> "FastGoldenFixture":
        if not self.cases:
            raise ValueError("Fast Golden fixture must contain cases")
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Fast Golden fixture contains duplicate case ids")
        mismatched_versions = [
            case.id for case in self.cases if case.dataset_version != self.dataset_version
        ]
        if mismatched_versions:
            raise ValueError(
                "case dataset_version must match fixture dataset_version: "
                + ", ".join(mismatched_versions)
            )
        return self


def adapt_legacy_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a v1 smoke fixture into the v2 case shape without touching it."""

    expected = dict(case["expected"])
    evidence_status = str(expected["evidence_status"])
    scenario_type = str(case["scenario_type"])
    category: FastCategory = (
        "NO_EVIDENCE" if evidence_status == "NO_EVIDENCE" else "GROUNDED_ADVICE"
    )
    citation_ids = [str(item) for item in expected.get("must_cite_source_ids") or []]
    normalized = FastGoldenCase(
        id=str(case["id"]),
        fixture_only=True,
        dataset_version="legacy-v1",
        source="expert",
        category=category,
        artifact="ADVICE",
        query=str(case["query"]),
        retrieval_status=str(case["retrieval_status"]),
        incident_context=dict(case.get("incident_context") or {}),
        knowledge_hits=[
            KnowledgeHitFixture.model_validate(hit) for hit in case.get("knowledge_hits") or []
        ],
        expected_outcome="READY",
        evidence_status=evidence_status,
        must_cite_source_ids=citation_ids,
        forbidden_source_ids=[],
        required_substrings=[
            str(item) for item in expected.get("required_substrings") or []
        ],
        forbidden_substrings=[
            str(item) for item in expected.get("forbidden_substrings") or []
        ],
        expected_risk="P1" if scenario_type in {"DEVICE_ANOMALY", "CROWD_ALERT"} else "P3",
        requires_human_approval=scenario_type in {"DEVICE_ANOMALY", "CROWD_ALERT"},
        required_tools=[],
        expected_actions=(
            ["ADOPT", "IGNORE"] if citation_ids else ["IGNORE", "PROCEED_WITHOUT_WAITING"]
        ),
        expected_model_calls=["context_trigger", "router", "memory_ops"],
        allowed_degradations=[],
        expected_sse_events=["ADVICE_PENDING", "ADVICE_READY"],
        failure_mode=f"legacy_smoke_{scenario_type.lower()}",
    )
    return normalized.model_dump(mode="json")


def evaluate_fast_golden_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one Fast case and return its deterministic contract report record."""

    normalized = FastGoldenCase.model_validate(case)
    checks = [
        "artifact",
        "expected_outcome",
        "evidence_status",
        "citation_contract",
        "risk",
        "human_gate",
        "tools",
        "actions",
        "model_calls",
        "degradations",
        "sse_events",
        "source_version",
    ]
    return {
        "id": normalized.id,
        "dataset_version": normalized.dataset_version,
        "source": normalized.source,
        "category": normalized.category,
        "artifact": normalized.artifact,
        "metric": "fast_golden_contract",
        "status": "PASS",
        "checks": checks,
    }

__all__ = [
    "CaseSchemaModel",
    "FastCategory",
    "FastGoldenCase",
    "FastGoldenFixture",
    "KnowledgeHitFixture",
    "NO_EVIDENCE_TEXT",
    "adapt_legacy_case",
]
