from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.unified_agent_uat.evidence import EvidenceRun
from scripts.unified_agent_uat.cli import main as evidence_cli_main
from scripts.unified_agent_uat.validation import validate_evidence


def test_create_run_builds_simulator_only_evidence_contract(tmp_path):
    output_root = tmp_path / "unified-agent-uat"
    created_at = datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc)

    run = EvidenceRun.create(
        output_root,
        run_id="UAT-20260803T093000Z-AB12CD34",
        now=created_at,
    )

    assert run.path == output_root / "UAT-20260803T093000Z-AB12CD34"
    assert {path.name for path in run.path.iterdir()} == {
        "artifacts",
        "failures",
        "logs",
        "manifest.json",
        "screenshots",
        "steps",
    }
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": 1,
        "uat_run_id": "UAT-20260803T093000Z-AB12CD34",
        "status": "RUNNING",
        "created_at": "2026-08-03T09:30:00Z",
        "completed_at": None,
        "architecture": {
            "business_data": "PostgreSQL",
            "queue": "Redis Streams",
            "vector_store": "ChromaDB",
            "generative_model": "deepseek-v4-flash",
        },
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "entrypoint": "/simulator/wecom/",
            "real_wecom_enabled": False,
        },
        "baseline": None,
        "steps": [],
    }

    with pytest.raises(FileExistsError, match="already exists"):
        EvidenceRun.create(output_root, run_id=run.run_id, now=created_at)

    with pytest.raises(ValueError, match="invalid uat_run_id"):
        EvidenceRun.create(output_root, run_id="../escape", now=created_at)


def test_failed_step_is_redacted_and_seals_the_run_without_overwriting_evidence(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T100000Z-FAIL0001",
        now=datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
    )

    result_path = run.record_step(
        "E2E-00",
        status="FAILED",
        evidence={
            "business_ids": {"trace_id": "trace-e2e-00"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [
                {
                    "name": "真实企微保持禁用",
                    "passed": False,
                    "actual": "意外启用",
                }
            ],
            "artifacts": {
                "diagnostics": {
                    "channel": "wecom-simulator",
                    "authorization": "Bearer should-not-leak",
                    "nested": {"password": "should-not-leak-either"},
                }
            },
        },
        now=datetime(2026, 8, 3, 10, 1, tzinfo=timezone.utc),
    )

    assert result_path == run.path / "steps" / "E2E-00.json"
    assert (run.path / "failures" / "E2E-00.json").read_bytes() == result_path.read_bytes()
    artifact = json.loads(
        (run.path / "artifacts" / "E2E-00" / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert artifact["authorization"] == "<redacted>"
    assert artifact["nested"]["password"] == "<redacted>"
    all_evidence = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run.path.rglob("*.json")
    )
    assert "should-not-leak" not in all_evidence

    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
    assert manifest["completed_at"] == "2026-08-03T10:01:00Z"
    assert manifest["steps"][0]["id"] == "E2E-00"
    assert manifest["steps"][0]["result"] == "steps/E2E-00.json"
    assert manifest["steps"][0]["failure"] == "failures/E2E-00.json"

    with pytest.raises(RuntimeError, match="sealed"):
        run.record_step(
            "E2E-00",
            status="PASSED",
            evidence={"business_ids": {}, "references": [], "assertions": [], "artifacts": {}},
        )


def test_invalid_step_input_does_not_leave_partial_evidence(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T101500Z-ATOMIC01",
        now=datetime(2026, 8, 3, 10, 15, tzinfo=timezone.utc),
    )
    manifest_before = (run.path / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="invalid artifact name"):
        run.record_step(
            "E2E-00",
            status="PASSED",
            evidence={
                "business_ids": {"trace_id": "trace-atomic"},
                "references": ["GET /api/v1/admin/diagnostics"],
                "assertions": [{"name": "证据写入原子化", "passed": True}],
                "artifacts": {
                    "valid-first": {"status": "ok"},
                    "../escape": {"status": "invalid"},
                },
            },
        )

    assert (run.path / "manifest.json").read_bytes() == manifest_before
    assert not (run.path / "steps" / "E2E-00.json").exists()
    assert not (run.path / "artifacts" / "E2E-00").exists()


def test_run_records_one_immutable_master_data_baseline(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T102000Z-BASELINE",
        now=datetime(2026, 8, 3, 10, 20, tzinfo=timezone.utc),
    )
    snapshot = {
        "schema_version": 1,
        "captured_at": 1785752400.0,
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "scope": {
            "organization_name": "悦山文旅集团",
            "venue": {"id": "venue-yueshan", "name": "悦山景区", "status": "ACTIVE"},
        },
        "master_data": {
            "users": [{"id": "user-li-ming", "username": "li-ming"}],
            "simulator_identities": [
                {
                    "id": "identity-li-ming",
                    "channel": "WECOM_SIMULATOR",
                    "user_id": "user-li-ming",
                }
            ],
            "published_sops": [{"id": 1, "title": "观光车雨后复运与异常异响处置", "version": "2.1"}],
            "signed_experts": [{"id": "expert-1", "display_name": "张建国"}],
            "approval_rules": [{"code": "SEND_CRITICAL_DISPATCH_ALERT", "approval_required": True}],
        },
        "process_counts": {"sessions": 0, "events": 0, "tasks": 0, "approvals": 0},
    }

    baseline_path = run.record_baseline(snapshot)

    assert baseline_path == run.path / "artifacts" / "uat-baseline.json"
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == snapshot
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["baseline"]["path"] == "artifacts/uat-baseline.json"
    assert manifest["baseline"]["sha256"] == sha256(baseline_path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="baseline already exists"):
        run.record_baseline(snapshot)


def test_validator_accepts_consistent_running_evidence_package(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T103000Z-VALID001",
        now=datetime(2026, 8, 3, 10, 30, tzinfo=timezone.utc),
    )
    run.record_step(
        "E2E-03",
        status="PASSED",
        evidence={
            "business_ids": {
                "trace_id": "trace-e2e-03",
                "event_id": "SJ-20260803-VALID001",
            },
            "references": ["GET /api/v1/admin/events/SJ-20260803-VALID001"],
            "assertions": [
                {"name": "事件引用正式 SOP", "passed": True, "actual": "SOP-001"},
            ],
            "model_calls": [
                {
                    "call_id": "llm-call-e2e-03",
                    "agent": "Router",
                    "model": "deepseek-v4-flash",
                    "is_mock": False,
                }
            ],
            "artifacts": {
                "event": {"event_id": "SJ-20260803-VALID001", "status": "OPEN"},
            },
        },
        now=datetime(2026, 8, 3, 10, 31, tzinfo=timezone.utc),
    )

    report = validate_evidence(
        run.path,
        registry_path=Path("src/memory_palace/config/feature_registry.yaml"),
    )

    assert report.valid is True
    assert report.errors == ()


def test_validator_rejects_missing_files_empty_ids_references_and_mock_models(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T110000Z-INVALID1",
        now=datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc),
    )
    result_path = run.record_step(
        "E2E-03",
        status="PASSED",
        evidence={
            "business_ids": {"event_id": "SJ-20260803-INVALID1"},
            "references": ["GET /api/v1/admin/events/SJ-20260803-INVALID1"],
            "assertions": [{"name": "事件创建", "passed": True}],
            "model_calls": [
                {
                    "call_id": "llm-call-invalid",
                    "agent": "Router",
                    "model": "deepseek-v4-flash",
                    "is_mock": False,
                }
            ],
            "artifacts": {"event": {"event_id": "SJ-20260803-INVALID1"}},
        },
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["business_ids"]["event_id"] = ""
    result["references"] = []
    result["model_calls"][0]["is_mock"] = True
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    missing_artifact = run.path / result["artifacts"][0]["path"]
    missing_artifact.unlink()
    manifest_path = run.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["steps"][0]["sha256"] = sha256(result_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = validate_evidence(run.path)

    assert report.valid is False
    assert any("empty business id" in error for error in report.errors)
    assert any("without non-empty references" in error for error in report.errors)
    assert any("mock or unsupported model call" in error for error in report.errors)
    assert any("artifact file is missing" in error for error in report.errors)


def test_validator_rejects_sensitive_values_even_after_checksums_are_updated(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T113000Z-SECRET01",
        now=datetime(2026, 8, 3, 11, 30, tzinfo=timezone.utc),
    )
    result_path = run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-secret-check"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "运行配置可读", "passed": True}],
            "artifacts": {"diagnostics": {"channel": "wecom-simulator"}},
        },
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    artifact_path = run.path / result["artifacts"][0]["path"]
    artifact_path.write_text(
        json.dumps({"authorization": "Bearer leaked-token"}, indent=2) + "\n",
        encoding="utf-8",
    )
    result["artifacts"][0]["sha256"] = sha256(artifact_path.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = run.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["steps"][0]["sha256"] = sha256(result_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = validate_evidence(run.path)

    assert report.valid is False
    assert any("sensitive field" in error and "authorization" in error for error in report.errors)


def test_validator_rejects_ready_registry_entry_without_current_run_evidence(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T120000Z-READY001",
        now=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )
    registry_path = tmp_path / "feature_registry.yaml"
    registry_path.write_text(
        "uat_journeys:\n"
        "  - id: E2E-00\n"
        "    name: 运行配置\n"
        "    covers: []\n"
        "    status: READY\n"
        "    evidence: []\n",
        encoding="utf-8",
    )

    report = validate_evidence(run.path, registry_path=registry_path)

    assert report.valid is False
    assert any("READY without current-run evidence" in error for error in report.errors)


def test_complete_seals_only_a_valid_all_passed_run(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T123000Z-COMPLETE",
        now=datetime(2026, 8, 3, 12, 30, tzinfo=timezone.utc),
    )
    with pytest.raises(RuntimeError, match="at least one recorded step"):
        run.complete(now=datetime(2026, 8, 3, 12, 31, tzinfo=timezone.utc))

    run.record_baseline(
        {
            "channel": {
                "mode": "WECOM_SIMULATOR_ONLY",
                "identity_channel": "WECOM_SIMULATOR",
                "real_wecom_enabled": False,
            },
            "process_counts": {"sessions": 0, "events": 0},
        }
    )
    run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-complete"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "真实企微保持禁用", "passed": True}],
            "artifacts": {"diagnostics": {"channel": "wecom-simulator"}},
        },
    )

    manifest_path = run.complete(
        now=datetime(2026, 8, 3, 12, 32, tzinfo=timezone.utc),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETED"
    assert manifest["completed_at"] == "2026-08-03T12:32:00Z"
    with pytest.raises(RuntimeError, match="sealed"):
        run.complete()


def test_cli_initializes_and_validates_a_run(tmp_path, capsys):
    run_id = "UAT-20260803T130000Z-CLI00001"

    assert evidence_cli_main(["init", "--output-root", str(tmp_path), "--run-id", run_id]) == 0
    init_output = json.loads(capsys.readouterr().out)
    assert init_output["uat_run_id"] == run_id
    assert Path(init_output["path"]) == tmp_path / run_id

    assert evidence_cli_main(["validate", "--run", str(tmp_path / run_id)]) == 0
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output == {"valid": True, "errors": []}


def test_cli_bootstrap_records_the_formal_api_baseline(tmp_path, capsys, monkeypatch):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T131500Z-BOOTCLI1",
        now=datetime(2026, 8, 3, 13, 15, tzinfo=timezone.utc),
    )
    snapshot = {
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "process_counts": {"sessions": 0, "events": 0},
    }

    async def bootstrap(_config):
        return SimpleNamespace(
            baseline_snapshot=snapshot,
            venue_id="venue-yueshan",
            user_count=7,
            identity_count=7,
        )

    monkeypatch.setattr(
        "scripts.unified_agent_uat.cli.UATBootstrapConfig.from_environment",
        lambda: object(),
    )
    monkeypatch.setattr(
        "scripts.unified_agent_uat.cli.bootstrap_uat_master_data",
        bootstrap,
    )

    assert evidence_cli_main(["bootstrap", "--run", str(run.path)]) == 0

    output = json.loads(capsys.readouterr().out)
    baseline_path = Path(output["baseline"])
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert baseline_path == run.path / "artifacts" / "uat-baseline.json"
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == snapshot
    assert manifest["baseline"]["path"] == "artifacts/uat-baseline.json"
