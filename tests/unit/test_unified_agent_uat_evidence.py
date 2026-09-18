from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.unified_agent_uat.evidence import EvidenceRun
from scripts.unified_agent_uat.cli import main as evidence_cli_main
from scripts.unified_agent_uat.validation import validate_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        "api",
        "artifacts",
        "browser-console.json",
        "pgvector-retrieval.json",
        "db-assertions.json",
        "evidence-validation.json",
        "execution-report.md",
        "failures",
        "llm-calls.json",
        "logs",
        "manifest.json",
        "queue-recovery.json",
        "screenshots",
        "steps",
        "traces",
    }
    for name in (
        "browser-console.json",
        "pgvector-retrieval.json",
        "db-assertions.json",
        "evidence-validation.json",
        "llm-calls.json",
        "queue-recovery.json",
    ):
        scaffold = json.loads((run.path / name).read_text(encoding="utf-8"))
        assert scaffold == {
            "schema_version": 1,
            "uat_run_id": "UAT-20260803T093000Z-AB12CD34",
            "records": [],
        }
    assert "UAT-20260803T093000Z-AB12CD34" in (run.path / "execution-report.md").read_text(
        encoding="utf-8"
    )
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
            "vector_store": "PostgreSQL pgvector",
            "generative_model": "deepseek-flash",
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
                    "external_ref": "/api/v1/assistant/attachments/private/content",
                    "thumbnail_url": "/api/v1/assistant/attachments/private/thumbnail",
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
    assert artifact["external_ref"] == "<redacted>"
    assert artifact["thumbnail_url"] == "<redacted>"
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


def test_baseline_recording_recovers_after_interruption_between_file_replacements(tmp_path, monkeypatch):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T102500Z-BASEATOM",
        now=datetime(2026, 8, 3, 10, 25, tzinfo=timezone.utc),
    )
    snapshot = {
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "process_counts": {"sessions": 0, "events": 0},
    }
    manifest_path = run.path / "manifest.json"
    original_replace = Path.replace
    interrupted = False

    def interrupt_manifest_replace(path, target):
        nonlocal interrupted
        if Path(target) == manifest_path and not interrupted:
            interrupted = True
            raise OSError("simulated interruption")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_manifest_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        run.record_baseline(snapshot)
    monkeypatch.setattr(Path, "replace", original_replace)

    baseline_path = run.record_baseline(snapshot)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == snapshot
    assert manifest["baseline"]["path"] == "artifacts/uat-baseline.json"
    assert not any(path.name.startswith(".uat-baseline") for path in run.path.iterdir())


def test_record_step_recovers_pending_baseline_before_updating_manifest(tmp_path, monkeypatch):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T102700Z-BASESTEP",
        now=datetime(2026, 8, 3, 10, 27, tzinfo=timezone.utc),
    )
    snapshot = {
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "process_counts": {"sessions": 0},
    }
    manifest_path = run.path / "manifest.json"
    original_replace = Path.replace
    interrupted = False

    def interrupt_manifest_replace(path, target):
        nonlocal interrupted
        if Path(target) == manifest_path and not interrupted:
            interrupted = True
            raise OSError("simulated interruption")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_manifest_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        run.record_baseline(snapshot)
    monkeypatch.setattr(Path, "replace", original_replace)

    run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-baseline-recovery"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "baseline 已恢复", "passed": True}],
        },
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["baseline"]["path"] == "artifacts/uat-baseline.json"
    assert manifest["steps"][0]["id"] == "E2E-00"
    assert not (run.path / ".uat-baseline.pending").exists()


def test_baseline_retry_discards_unprepared_staging_directory(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T102900Z-BASEPREP",
        now=datetime(2026, 8, 3, 10, 29, tzinfo=timezone.utc),
    )
    pending = run.path / ".uat-baseline.pending"
    pending.mkdir()
    (pending / "uat-baseline.json").write_text("{}\n", encoding="utf-8")
    snapshot = {
        "channel": {
            "mode": "WECOM_SIMULATOR_ONLY",
            "identity_channel": "WECOM_SIMULATOR",
            "real_wecom_enabled": False,
        },
        "process_counts": {"sessions": 0},
    }

    baseline_path = run.record_baseline(snapshot)

    assert json.loads(baseline_path.read_text(encoding="utf-8")) == snapshot
    assert not pending.exists()


def test_validator_accepts_consistent_running_evidence_package(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T103000Z-VALID001",
        now=datetime(2026, 8, 3, 10, 30, tzinfo=timezone.utc),
    )
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
                    "model": "deepseek-flash",
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


def test_validator_rejects_run_without_pristine_baseline(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T104500Z-NOBASE01",
        now=datetime(2026, 8, 3, 10, 45, tzinfo=timezone.utc),
    )

    report = validate_evidence(run.path)

    assert report.valid is False
    assert "UAT baseline is missing" in report.errors


def test_validator_rejects_incomplete_evidence_scaffold(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T105000Z-SCAFFOLD",
        now=datetime(2026, 8, 3, 10, 50, tzinfo=timezone.utc),
    )
    run.record_baseline(
        {
            "channel": {
                "mode": "WECOM_SIMULATOR_ONLY",
                "identity_channel": "WECOM_SIMULATOR",
                "real_wecom_enabled": False,
            },
            "process_counts": {"sessions": 0},
        }
    )
    (run.path / "api").rmdir()
    (run.path / "execution-report.md").unlink()

    report = validate_evidence(run.path)

    assert report.valid is False
    assert "required evidence directory is missing: api" in report.errors
    assert "required evidence file is missing: execution-report.md" in report.errors


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
                    "model": "deepseek-flash",
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
        json.dumps(
            {
                "authorization": "Bearer leaked-token",
                "external_ref": "/api/v1/assistant/attachments/private/content",
            },
            indent=2,
        )
        + "\n",
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
    assert any("sensitive field" in error and "external_ref" in error for error in report.errors)


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


def test_validator_rejects_ready_registry_evidence_that_does_not_exist_in_run(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T121500Z-READYPTH",
        now=datetime(2026, 8, 3, 12, 15, tzinfo=timezone.utc),
    )
    run.record_baseline(
        {
            "channel": {
                "mode": "WECOM_SIMULATOR_ONLY",
                "identity_channel": "WECOM_SIMULATOR",
                "real_wecom_enabled": False,
            },
            "process_counts": {"sessions": 0},
        }
    )
    run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-ready-path"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "运行配置可读", "passed": True}],
        },
    )
    registry_path = tmp_path / "feature_registry.yaml"
    registry_path.write_text(
        "uat_journeys:\n"
        "  - id: E2E-00\n"
        "    name: 运行配置\n"
        "    covers: []\n"
        "    status: READY\n"
        f"    evidence: [docs/verification/unified-agent-uat/{run.run_id}/api/missing.json]\n",
        encoding="utf-8",
    )

    report = validate_evidence(run.path, registry_path=registry_path)

    assert report.valid is False
    assert any("registry evidence file is missing" in error for error in report.errors)


def test_validator_requires_ready_registry_to_reference_matching_step_file(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T122000Z-READYSTP",
        now=datetime(2026, 8, 3, 12, 20, tzinfo=timezone.utc),
    )
    run.record_baseline(
        {
            "channel": {
                "mode": "WECOM_SIMULATOR_ONLY",
                "identity_channel": "WECOM_SIMULATOR",
                "real_wecom_enabled": False,
            },
            "process_counts": {"sessions": 0},
        }
    )
    run.record_step(
        "E2E-00",
        status="PASSED",
        evidence={
            "business_ids": {"trace_id": "trace-ready-step"},
            "references": ["GET /api/v1/admin/diagnostics"],
            "assertions": [{"name": "运行配置可读", "passed": True}],
        },
    )
    registry_path = tmp_path / "feature_registry.yaml"
    prefix = f"docs/verification/unified-agent-uat/{run.run_id}"
    registry_path.write_text(
        "uat_journeys:\n"
        "  - id: E2E-00\n"
        "    name: 运行配置\n"
        "    covers: []\n"
        "    status: READY\n"
        f"    evidence: [{prefix}/artifacts/uat-baseline.json]\n",
        encoding="utf-8",
    )

    wrong_report = validate_evidence(run.path, registry_path=registry_path)

    assert any("READY without current-run evidence" in error for error in wrong_report.errors)

    registry_path.write_text(
        "uat_journeys:\n"
        "  - id: E2E-00\n"
        "    name: 运行配置\n"
        "    covers: []\n"
        "    status: READY\n"
        f"    evidence: [{prefix}/steps/E2E-00.json]\n",
        encoding="utf-8",
    )

    assert validate_evidence(run.path, registry_path=registry_path).valid is True


def test_validator_rejects_registry_evidence_path_traversal(tmp_path):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260803T122500Z-READYESC",
        now=datetime(2026, 8, 3, 12, 25, tzinfo=timezone.utc),
    )
    registry_path = tmp_path / "feature_registry.yaml"
    registry_path.write_text(
        "uat_journeys:\n"
        "  - id: E2E-00\n"
        "    name: 运行配置\n"
        "    covers: []\n"
        "    status: READY\n"
        f"    evidence: [docs/verification/unified-agent-uat/{run.run_id}/../outside.json]\n",
        encoding="utf-8",
    )

    report = validate_evidence(run.path, registry_path=registry_path)

    assert any("registry evidence path escapes evidence run" in error for error in report.errors)


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


def test_cli_initializes_a_run_that_requires_bootstrap_before_validation(tmp_path, capsys):
    run_id = "UAT-20260803T130000Z-CLI00001"

    assert evidence_cli_main(["init", "--output-root", str(tmp_path), "--run-id", run_id]) == 0
    init_output = json.loads(capsys.readouterr().out)
    assert init_output["uat_run_id"] == run_id
    assert Path(init_output["path"]) == tmp_path / run_id

    assert evidence_cli_main(["validate", "--run", str(tmp_path / run_id)]) == 1
    validation_output = json.loads(capsys.readouterr().out)
    assert validation_output == {"valid": False, "errors": ["UAT baseline is missing"]}


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


def test_cli_executes_selected_formal_journey_steps_with_an_explicit_attachment(
    tmp_path,
    capsys,
    monkeypatch,
):
    run = EvidenceRun.create(
        tmp_path,
        run_id="UAT-20260804T130000Z-EXECUTE1",
        now=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
    )
    attachment_path = tmp_path / "right-rear-wheel.png"
    attachment_path.write_bytes(b"\x89PNG\r\n\x1a\nformal-uat-image")
    config = SimpleNamespace(base_url="http://127.0.0.1:8082")
    captured = {}

    async def execute(active_config, active_run, step_ids, *, attachment_path, **_kwargs):
        captured.update(
            {
                "config": active_config,
                "run": active_run,
                "step_ids": list(step_ids),
                "attachment_path": attachment_path,
            }
        )
        return [active_run.path / "steps" / f"{step_id}.json" for step_id in step_ids]

    monkeypatch.setattr(
        "scripts.unified_agent_uat.cli.UATJourneyConfig.from_environment",
        lambda: config,
    )
    monkeypatch.setattr("scripts.unified_agent_uat.cli.run_uat_steps", execute)

    assert evidence_cli_main(
        [
            "execute",
            "--run",
            str(run.path),
            "--steps",
            "E2E-00",
            "E2E-01",
            "E2E-02",
            "--attachment",
            str(attachment_path),
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "uat_run_id": run.run_id,
        "recorded": [
            str(run.path / "steps" / "E2E-00.json"),
            str(run.path / "steps" / "E2E-01.json"),
            str(run.path / "steps" / "E2E-02.json"),
        ],
    }
    assert captured == {
        "config": config,
        "run": EvidenceRun(path=run.path.resolve(), run_id=run.run_id),
        "step_ids": ["E2E-00", "E2E-01", "E2E-02"],
        "attachment_path": attachment_path,
    }


def test_bootstrap_uat_wrapper_runs_directly_outside_repository(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "bootstrap_uat.py"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--run RUN" in result.stdout
