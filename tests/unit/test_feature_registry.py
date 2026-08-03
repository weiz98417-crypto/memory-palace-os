from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.memory_palace.config.feature_registry import (
    FeatureRegistryError,
    _release_gate_passed,
    load_feature_registry,
    registry_snapshot,
    validate_feature_registry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def registry_with_delivery_evidence(tmp_path, *item_ids, ready_uat_ids=()):
    registry = deepcopy(load_feature_registry())
    for item in registry["items"]:
        if item["id"] in item_ids:
            item["evidence"]["browser"] = [f"browser:{item['id']}"]
            item["evidence"]["live"] = [f"live:{item['id']}"]
            item["evidence"]["uat"] = [f"uat:{item['id']}"]
    for journey in registry["uat_journeys"]:
        if journey["id"] in ready_uat_ids:
            journey["status"] = "READY"
            journey["evidence"] = [f"uat:{journey['id']}"]
        else:
            journey["status"] = "BLOCKED"
            journey["evidence"] = []
    path = tmp_path / "feature_registry.yaml"
    path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def registry_without_delivery_evidence(tmp_path, *item_ids):
    registry = deepcopy(load_feature_registry())
    selected_ids = set(item_ids) or {
        item["id"]
        for item in registry["items"]
        if item["category"] in {"business", "agent"}
    }
    for item in registry["items"]:
        if item["id"] in selected_ids:
            for evidence_kind in ("browser", "live", "uat"):
                item["evidence"][evidence_kind] = []
    path = tmp_path / "feature_registry_without_delivery.yaml"
    path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_feature_registry_covers_prd_business_agents_and_uat():
    registry = load_feature_registry()
    items = registry["items"]
    business_ids = {item["id"] for item in items if item["category"] == "business"}
    agent_ids = {item["id"] for item in items if item["category"] == "agent"}

    assert business_ids == {f"MVP-BIZ-{number:03d}" for number in range(1, 21)}
    assert agent_ids == {
        "ContextTrigger",
        "Router",
        "Commander",
        "MemoryOps",
        "Persona",
        "PersonaExtract",
        "TodoWrite",
        "Watcher",
    }
    assert registry["baseline"] == "PRD-memory-palace-unified-agent-experience-mvp.md"
    assert registry["baseline_documents"] == [
        "PRD-memory-palace-unified-agent-experience-mvp.md",
        "docs/product/unified-agent-page-map.md",
        "docs/product/unified-agent-demo-journey.md",
    ]
    assert {journey["id"] for journey in registry["uat_journeys"]} == {
        *(f"E2E-{number:02d}" for number in range(17)),
        *(f"UAT-F{number:02d}" for number in range(1, 14)),
    }
    covered_business_ids = {
        feature_id
        for journey in registry["uat_journeys"]
        for feature_id in journey["covers"]
        if feature_id.startswith("MVP-BIZ-")
    }
    assert covered_business_ids == business_ids


def test_feature_registry_has_no_unproven_ready_claims():
    registry = load_feature_registry()

    assert all(item["status"] != "READY" for item in registry["items"])
    for item in registry["items"]:
        if item["status"] == "DISABLED_REQUIRES_CONFIG":
            assert item["interactive"] is False
            assert item["external_config"]
            assert item["blocked_reason"]


def test_unified_agent_registry_removes_persona_admin_surface_and_old_persona_features():
    registry = load_feature_registry()
    serialized = yaml.safe_dump(registry, allow_unicode=True, sort_keys=False)
    items = {item["id"]: item for item in registry["items"]}

    assert "/admin/personas" not in serialized
    assert items["MVP-BIZ-014"]["name"] == "专家档案与经验授权"
    assert items["MVP-BIZ-015"]["name"] == "统一助手专家访谈与萃取"
    assert items["MVP-BIZ-016"]["name"] == "经验审核、发布与统一助手复用"
    assert items["Persona"]["entrypoints"] == ["assistant:/"]
    assert "POST /assistant/messages" in items["Persona"]["apis"]


def test_all_registry_evidence_references_existing_files():
    registry = load_feature_registry()

    for item in registry["items"]:
        for evidence_kind, references in item["evidence"].items():
            for reference in references:
                evidence_path = reference.split("::", 1)[0]
                assert (PROJECT_ROOT / evidence_path).is_file(), (
                    f"{item['id']} references missing {evidence_kind} evidence: {reference}"
                )


def test_new_uat_journeys_start_blocked_without_reusing_legacy_evidence():
    registry = load_feature_registry()

    for journey in registry["uat_journeys"]:
        assert journey["status"] == "BLOCKED"
        assert journey["evidence"] == []


def test_registry_declares_event_watcher_candidate_recovery_and_dossier_contracts():
    registry = load_feature_registry()
    items = {item["id"]: item for item in registry["items"]}

    closure = items["MVP-BIZ-006"]
    assert "POST /admin/events/{event_id}/watcher-check" in closure["apis"]
    assert "POST /admin/events/{event_id}/experience-candidate/retry" in closure["apis"]
    assert "PostgreSQL.experience_candidate_attempts" in closure["data_dependencies"]
    assert {"EVENT_CLOSE_DENIED", "EXPERIENCE_CANDIDATE_CREATED", "EXPERIENCE_CANDIDATE_RETRY"} <= set(closure["audit_events"])
    assert "EXPERIENCE_CANDIDATE_RETRY_FAILED" in closure["error_codes"]

    watcher = items["Watcher"]
    assert "POST /admin/events/{event_id}/watcher-check" in watcher["apis"]
    assert "tests/integration/test_event_watcher_check.py::test_event_watcher_check_persists_complete_evidence_snapshot" in watcher["tests"]["integration"]

    recovery = items["MVP-PLATFORM-HEALTH"]
    assert "GET /admin/recovery-runs" in recovery["apis"]
    assert "PostgreSQL.runtime_recovery_runs" in recovery["data_dependencies"]
    assert "RUNTIME_RECOVERY_AUDIT" in recovery["audit_events"]
    assert "tests/integration/test_runtime_recovery_audit.py::test_application_recovery_persists_global_run_and_all_phase_counts" in recovery["tests"]["integration"]

    deepseek = items["MVP-INTEGRATION-DEEPSEEK"]
    assert "GET /admin/events/{event_id}" in deepseek["apis"]
    assert "PostgreSQL.llm_call_logs" in deepseek["data_dependencies"]
    assert "tests/integration/test_event_dossier.py::test_event_dossier_is_human_readable_and_keeps_technical_ids_folded" in deepseek["tests"]["integration"]


def test_feature_registry_rejects_ready_without_complete_evidence():
    invalid_registry = {
        "schema_version": 1,
        "release": "test",
        "uat_journeys": [],
        "items": [
            {
                "id": "TEST-001",
                "name": "Invalid ready feature",
                "category": "platform",
                "owner": "engineering",
                "status": "READY",
                "interactive": True,
                "entrypoints": ["/test"],
                "roles": ["admin"],
                "tenant_scope": "venue_id",
                "apis": ["GET /test"],
                "services": ["test"],
                "agents": [],
                "permission": "AUTHENTICATED",
                "data_dependencies": ["PostgreSQL"],
                "audit_events": ["TESTED"],
                "trace_query": "GET /admin/audit-logs",
                "error_codes": ["TEST_FAILED"],
                "tests": {"unit": [], "integration": [], "browser": [], "live": [], "uat": []},
                "evidence": {"automated": [], "browser": [], "live": [], "uat": []},
                "backup_restore": "none",
                "external_config": [],
                "known_limitations": [],
                "blocked_reason": "",
                "references": {"code": [], "openspec": [], "docs": [], "release": []},
            }
        ],
    }

    with pytest.raises(FeatureRegistryError, match="READY"):
        validate_feature_registry(invalid_registry)


def test_runtime_snapshot_keeps_missing_runtime_features_blocked_and_explains_evidence():
    snapshot = registry_snapshot(evidence={})
    login = next(item for item in snapshot["items"] if item["id"] == "MVP-BIZ-001")

    assert login["declared_status"] == "BLOCKED"
    assert login["status"] == "BLOCKED"
    assert login["acceptance"]["required"]
    assert login["acceptance"]["satisfied"] == []
    assert login["acceptance"]["missing"] == [
        "成功登录审计",
        "令牌刷新审计",
        "安全退出审计",
        "浏览器验收证据",
        "Live 验收证据",
        "UAT 验收证据",
    ]
    assert login["runtime_evidence"] == []
    assert snapshot["summary"]["business_ready"] == 0
    assert snapshot["summary"]["release_gate_passed"] is False


def test_message_intake_requires_one_trace_for_completed_agent_chain(tmp_path):
    path = registry_with_delivery_evidence(tmp_path, "MVP-BIZ-003")
    evidence = {
        "facts": {
            "message_runs.completed": [{"trace_id": "trace-message", "status": "COMPLETED"}],
            "agents.ContextTrigger.live_succeeded": {
                "agent_id": "ContextTrigger",
                "trace_id": "trace-message",
                "status": "SUCCEEDED",
                "is_mock": False,
            },
            "agents.Router.live_succeeded": {
                "agent_id": "Router",
                "trace_id": "trace-router-other",
                "status": "SUCCEEDED",
                "is_mock": False,
            },
            "agents.Commander.live_succeeded": {
                "agent_id": "Commander",
                "trace_id": "trace-message",
                "status": "SUCCEEDED",
                "is_mock": False,
            },
        },
        "integrations": {
            "deepseek": {
                "configured": True,
                "live_verified": True,
                "status": "READY",
                "evidence": {
                    "provider": "deepseek",
                    "status": "SUCCEEDED",
                    "is_mock": False,
                    "trace_id": "trace-unrelated-llm",
                },
            }
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    message_intake = next(item for item in snapshot["items"] if item["id"] == "MVP-BIZ-003")

    assert message_intake["status"] == "BLOCKED"
    assert "同 Trace 消息 Agent 链" in message_intake["acceptance"]["missing"]


def test_message_intake_rejects_same_trace_missing_one_required_agent(tmp_path):
    path = registry_with_delivery_evidence(tmp_path, "MVP-BIZ-003")
    trace_id = "trace-incomplete-message-chain"
    evidence = {
        "facts": {
            "message_runs.completed": [{"trace_id": trace_id, "status": "COMPLETED"}],
            **{
                f"agents.{agent_id}.live_succeeded": {
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                    "status": "SUCCEEDED",
                    "is_mock": False,
                }
                for agent_id in ("ContextTrigger", "Router", "MemoryOps")
            },
        },
        "integrations": {
            "deepseek": {
                "configured": True,
                "live_verified": True,
                "status": "READY",
                "evidence": {
                    "provider": "deepseek",
                    "status": "SUCCEEDED",
                    "is_mock": False,
                    "trace_id": trace_id,
                },
            }
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    message_intake = next(item for item in snapshot["items"] if item["id"] == "MVP-BIZ-003")

    assert message_intake["status"] == "BLOCKED"


def test_message_intake_accepts_one_attributable_success_trace(tmp_path):
    path = registry_with_delivery_evidence(tmp_path, "MVP-BIZ-003")
    trace_id = "trace-message-chain"
    evidence = {
        "facts": {
            "message_runs.completed": [{"trace_id": trace_id, "status": "COMPLETED"}],
            **{
                f"agents.{agent_id}.live_succeeded": {
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                    "status": "SUCCEEDED",
                    "is_mock": False,
                }
                for agent_id in ("ContextTrigger", "Router", "Commander", "MemoryOps")
            },
        },
        "integrations": {
            "deepseek": {
                "configured": True,
                "live_verified": True,
                "status": "READY",
                "evidence": {
                    "provider": "deepseek",
                    "status": "SUCCEEDED",
                    "is_mock": False,
                    "trace_id": trace_id,
                },
            }
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    message_intake = next(item for item in snapshot["items"] if item["id"] == "MVP-BIZ-003")
    chain = next(
        record for record in message_intake["runtime_evidence"] if record.get("kind") == "message_agent_chain"
    )

    assert message_intake["status"] == "READY"
    assert trace_id in {record.get("trace_id") for record in message_intake["runtime_evidence"]}
    assert chain["agents"] == ["ContextTrigger", "Router", "Commander", "MemoryOps"]


def test_agent_ready_requires_attributable_success_trace(tmp_path):
    path = registry_with_delivery_evidence(tmp_path, "Watcher")
    evidence = {
        "facts": {
            "agents.Watcher.live_succeeded": {
                "trace_id": "trace-watcher",
                "status": "SUCCEEDED",
                "is_mock": False,
            }
        },
        "integrations": {
            "deepseek": {
                "configured": True,
                "live_verified": True,
                "status": "READY",
                "evidence": {
                    "provider": "deepseek",
                    "status": "SUCCEEDED",
                    "is_mock": False,
                    "trace_id": "trace-latest-other-agent",
                },
            }
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    watcher = next(item for item in snapshot["items"] if item["id"] == "Watcher")

    assert watcher["status"] == "BLOCKED"
    assert "Watcher 归属明确的成功 Trace" in watcher["acceptance"]["missing"]

    evidence["facts"]["agents.Watcher.live_succeeded"]["agent_name"] = "Watcher"
    proven = registry_snapshot(path, evidence=evidence)
    proven_watcher = next(item for item in proven["items"] if item["id"] == "Watcher")

    assert proven_watcher["status"] == "READY"
    assert "trace-watcher" in {record.get("trace_id") for record in proven_watcher["runtime_evidence"]}


def test_business_ready_cannot_bypass_empty_browser_live_or_uat_evidence(tmp_path):
    path = registry_without_delivery_evidence(tmp_path, "MVP-BIZ-004")
    evidence = {
        "audits": {
            "EVENT_CREATED": [{"action": "EVENT_CREATED", "trace_id": "trace-event"}],
        },
        "facts": {"events.total": 1},
        "runtime": {"chromadb": "healthy"},
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    history_entry = next(item for item in snapshot["items"] if item["id"] == "MVP-BIZ-004")

    assert history_entry["status"] == "BLOCKED"
    assert {"浏览器验收证据", "Live 验收证据", "UAT 验收证据"} <= set(
        history_entry["acceptance"]["missing"]
    )


def test_runtime_snapshot_does_not_promote_database_facts_without_delivery_evidence(tmp_path):
    path = registry_without_delivery_evidence(tmp_path)
    actions = {
        "AUTH_LOGIN",
        "AUTH_REFRESH",
        "AUTH_LOGOUT",
        "EVENT_CREATED",
        "EVENT_UPDATED",
        "EVENT_CLOSED",
        "SESSION_CLOSED",
        "TASK_CREATED",
        "TASK_ASSIGNED",
        "TASK_STARTED",
        "TASK_FAILED",
        "TASK_RETRIED",
        "TASK_COMPLETED",
        "CONTROLLED_ACTION_REQUESTED",
        "APPROVAL_APPROVED",
        "APPROVAL_REJECTED",
        "KNOWLEDGE_CREATED",
        "KNOWLEDGE_UPDATED",
        "KNOWLEDGE_INDEX_REBUILT",
        "SOP_CREATED",
        "SOP_SUBMITTED",
        "SOP_REJECTED",
        "SOP_UPDATED",
        "SOP_PUBLISHED",
        "WATCHER_POLICY_CREATED",
        "WATCHER_POLICY_UPDATED",
        "WATCHER_RUN",
        "USER_CREATED",
        "USER_UPDATED",
        "USER_PASSWORD_RESET",
        "VENUE_CREATED",
        "SETTING_UPDATED",
        "CONFIG_RELOADED",
        "SKILL_RELOADED",
    }
    evidence = {
        "audits": {
            action: [{"action": action, "trace_id": f"trace-{action.lower()}"}]
            for action in actions
        },
        "facts": {
            "events.total": 2,
            "events.closed": 1,
            "message_runs.total": 4,
            "message_runs.completed": 1,
            "sessions.total": 4,
            "sessions.closed": 1,
            "tasks.total": 2,
            "tasks.done": 2,
            "approvals.approved": 1,
            "approvals.rejected": 1,
            "approvals.executed": 1,
            "push_logs.total": 0,
            "push_logs.reviewed": 0,
            "tool_invocations.total": 0,
            "knowledge.total": 2,
            "sops.published": 1,
            "personas.total": 0,
            "interviews.completed": 0,
            "watcher_policies.total": 1,
            "watcher_runs.succeeded": 4,
            "watcher_findings.assigned": 0,
            "watcher_findings.closed": 0,
            "users.total": 4,
            "venues.total": 2,
            "settings.total": 1,
        },
        "runtime": {
            "database": "healthy",
            "queue": "healthy",
            "chromadb": "healthy",
            "scheduler": "healthy",
        },
        "integrations": {
            "deepseek": {
                "configured": True,
                "live_verified": False,
                "status": "BLOCKED",
            }
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    ready_business = {
        item["id"]
        for item in snapshot["items"]
        if item["category"] == "business" and item["status"] == "READY"
    }

    assert ready_business == set()
    assert snapshot["summary"]["business_ready"] == 0
    assert all(
        item["status"] == "BLOCKED"
        for item in snapshot["items"]
        if item["category"] == "agent"
    )


def test_deepseek_status_requires_configuration_and_non_mock_live_success_evidence():
    missing = registry_snapshot(
        evidence={
            "integrations": {
                "deepseek": {
                    "configured": False,
                    "live_verified": False,
                    "status": "DISABLED_REQUIRES_CONFIG",
                }
            }
        }
    )
    configured = registry_snapshot(
        evidence={
            "integrations": {
                "deepseek": {
                    "configured": True,
                    "live_verified": False,
                    "status": "BLOCKED",
                }
            }
        }
    )
    live = registry_snapshot(
        evidence={
            "facts": {"llm_calls.event_dossier_visible": 1},
            "integrations": {
                "deepseek": {
                    "configured": True,
                    "live_verified": True,
                    "status": "READY",
                    "evidence": {
                        "provider": "deepseek",
                        "model_name": "deepseek-v4-flash",
                        "status": "SUCCEEDED",
                        "is_mock": False,
                        "trace_id": "trace-live-deepseek",
                    },
                }
            }
        }
    )

    def item(snapshot, item_id):
        return next(entry for entry in snapshot["items"] if entry["id"] == item_id)

    assert item(missing, "MVP-INTEGRATION-DEEPSEEK")["status"] == "DISABLED_REQUIRES_CONFIG"
    assert item(configured, "MVP-INTEGRATION-DEEPSEEK")["status"] == "BLOCKED"
    deepseek = item(live, "MVP-INTEGRATION-DEEPSEEK")
    assert deepseek["status"] == "READY"
    assert deepseek["runtime_evidence"][0]["trace_id"] == "trace-live-deepseek"
    assert all(
        entry["status"] == "BLOCKED"
        for entry in live["items"]
        if entry["category"] == "agent"
    )


def test_uat_journey_becomes_ready_only_when_every_covered_item_is_ready(tmp_path):
    path = registry_with_delivery_evidence(
        tmp_path,
        "MVP-BIZ-004",
        "MVP-BIZ-005",
        "MVP-BIZ-007",
        ready_uat_ids={"E2E-04"},
    )
    evidence = {
        "audits": {
            action: [{"action": action, "trace_id": f"trace-{action.lower()}"}]
            for action in {"EVENT_CREATED", "SESSION_CLOSED"}
        },
        "facts": {
            "events.total": 1,
            "message_runs.total": 1,
            "sessions.total": 1,
            "sessions.closed": 1,
        },
        "runtime": {"chromadb": "healthy"},
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    journeys = {journey["id"]: journey for journey in snapshot["uat_journeys"]}

    assert journeys["E2E-04"]["status"] == "READY"
    assert journeys["E2E-04"]["acceptance"]["missing"] == []
    assert journeys["E2E-03"]["status"] == "BLOCKED"
    assert "MemoryOps" in journeys["E2E-03"]["acceptance"]["missing"]
    assert "MVP-BIZ-003" in journeys["E2E-03"]["acceptance"]["missing"]


def test_uat_journey_stays_blocked_without_declared_acceptance_evidence(tmp_path):
    path = registry_with_delivery_evidence(
        tmp_path,
        "MVP-BIZ-004",
        "MVP-BIZ-005",
        "MVP-BIZ-007",
    )
    evidence = {
        "audits": {
            action: [{"action": action, "trace_id": f"trace-{action.lower()}"}]
            for action in {"EVENT_CREATED", "SESSION_CLOSED"}
        },
        "facts": {
            "events.total": 1,
            "message_runs.total": 1,
            "sessions.total": 1,
            "sessions.closed": 1,
        },
        "runtime": {"chromadb": "healthy"},
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    journey = next(item for item in snapshot["uat_journeys"] if item["id"] == "E2E-04")

    assert journey["status"] == "BLOCKED"
    assert "旅程验收证据" in journey["acceptance"]["missing"]


def test_uat_f12_accepts_safely_disabled_optional_channels(tmp_path):
    path = registry_with_delivery_evidence(
        tmp_path,
        "MVP-BIZ-020",
        ready_uat_ids={"UAT-F12"},
    )
    evidence = {
        "facts": {"settings.total": 1},
        "audits": {
            action: [{"action": action, "trace_id": f"trace-{action.lower()}"}]
            for action in {"SETTING_UPDATED", "CONFIG_RELOADED", "SKILL_RELOADED"}
        },
        "integrations": {
            **{
                integration_id: {
                    "configured": False,
                    "live_verified": False,
                    "status": "DISABLED_REQUIRES_CONFIG",
                    "safe_disabled_verified": True,
                }
                for integration_id in ("wechat", "sms", "voice")
            },
        },
    }

    snapshot = registry_snapshot(path, evidence=evidence)
    journeys = {journey["id"]: journey for journey in snapshot["uat_journeys"]}
    uat = journeys["UAT-F12"]

    assert uat["status"] == "READY"
    assert uat["acceptance"]["missing"] == []
    assert {
        "MVP-INTEGRATION-WECHAT",
        "MVP-INTEGRATION-SMS",
        "MVP-INTEGRATION-VOICE",
    } <= set(uat["acceptance"]["satisfied"])


def test_release_gate_requires_platform_uat_and_verified_safe_disable():
    registry = {
        "items": [
            {"id": "MVP-BIZ-001", "status": "READY"},
            {"id": "ContextTrigger", "status": "READY"},
            {"id": "MVP-PLATFORM-POSTGRES", "status": "READY"},
            {"id": "MVP-INTEGRATION-DEEPSEEK", "status": "READY"},
            {
                "id": "MVP-INTEGRATION-WECHAT",
                "status": "DISABLED_REQUIRES_CONFIG",
                "safe_disabled_verified": True,
            },
        ],
        "uat_journeys": [{"id": "E2E-00", "status": "READY"}],
    }

    assert _release_gate_passed(registry) is True

    registry["uat_journeys"][0]["status"] = "BLOCKED"
    assert _release_gate_passed(registry) is False

    registry["uat_journeys"][0]["status"] = "READY"
    registry["items"][-1]["safe_disabled_verified"] = False
    assert _release_gate_passed(registry) is False

    registry["items"][-1]["safe_disabled_verified"] = True
    registry["items"][2]["status"] = "BLOCKED"
    assert _release_gate_passed(registry) is False
