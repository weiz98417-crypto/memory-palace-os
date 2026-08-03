"""Create and maintain immutable unified-agent UAT evidence runs."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


_RUN_DIRECTORIES = ("artifacts", "failures", "logs", "screenshots", "steps")
_RUN_ID_PATTERN = re.compile(r"^UAT-\d{8}T\d{6}Z-[A-Z0-9]{8}$")
_STEP_ID_PATTERN = re.compile(r"^(?:E2E-\d{2}|UAT-F\d{2})$")
_ARTIFACT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "token",
    "access_token",
}


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_run_id(now: datetime) -> str:
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"UAT-{timestamp}-{uuid4().hex[:8].upper()}"


def _write_json(path: Path, value: Any) -> None:
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if str(key).lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class EvidenceRun:
    """A single append-only UAT evidence directory."""

    path: Path
    run_id: str

    @classmethod
    def create(
        cls,
        output_root: Path,
        *,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> "EvidenceRun":
        created_at = now or datetime.now(timezone.utc)
        resolved_run_id = run_id or _new_run_id(created_at)
        if not _RUN_ID_PATTERN.fullmatch(resolved_run_id):
            raise ValueError(f"invalid uat_run_id: {resolved_run_id}")
        run_path = output_root / resolved_run_id

        try:
            run_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise FileExistsError(f"evidence run already exists: {resolved_run_id}") from exc

        for directory in _RUN_DIRECTORIES:
            (run_path / directory).mkdir()

        manifest = {
            "schema_version": 1,
            "uat_run_id": resolved_run_id,
            "status": "RUNNING",
            "created_at": _utc_timestamp(created_at),
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
            "steps": [],
        }
        _write_json(run_path / "manifest.json", manifest)
        return cls(path=run_path, run_id=resolved_run_id)

    def record_step(
        self,
        step_id: str,
        *,
        status: str,
        evidence: Mapping[str, Any],
        now: datetime | None = None,
    ) -> Path:
        if not _STEP_ID_PATTERN.fullmatch(step_id):
            raise ValueError(f"invalid UAT step id: {step_id}")
        if status not in {"PASSED", "FAILED"}:
            raise ValueError(f"invalid UAT step status: {status}")

        manifest_path = self.path / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "RUNNING":
            raise RuntimeError(f"evidence run is sealed with status {manifest.get('status')}")

        result_path = self.path / "steps" / f"{step_id}.json"
        if result_path.exists() or any(step.get("id") == step_id for step in manifest.get("steps", [])):
            raise FileExistsError(f"evidence step already exists: {step_id}")

        recorded_at = now or datetime.now(timezone.utc)
        sanitized = _redact(deepcopy(dict(evidence)))
        artifact_payloads = sanitized.pop("artifacts", {})
        if not isinstance(artifact_payloads, Mapping):
            raise ValueError("evidence artifacts must be a mapping")

        normalized_artifacts: list[tuple[str, Any]] = []
        for name, payload in artifact_payloads.items():
            artifact_name = str(name)
            if not _ARTIFACT_NAME_PATTERN.fullmatch(artifact_name):
                raise ValueError(f"invalid artifact name: {artifact_name}")
            normalized_artifacts.append((artifact_name, payload))

        artifact_records = []
        artifact_directory = self.path / "artifacts" / step_id
        if normalized_artifacts:
            artifact_directory.mkdir(exist_ok=False)
        for artifact_name, payload in normalized_artifacts:
            artifact_path = artifact_directory / f"{artifact_name}.json"
            _write_json(artifact_path, payload)
            artifact_records.append(
                {
                    "name": artifact_name,
                    "path": artifact_path.relative_to(self.path).as_posix(),
                    "sha256": _file_sha256(artifact_path),
                }
            )

        step_result = {
            "schema_version": 1,
            "uat_run_id": self.run_id,
            "step_id": step_id,
            "status": status,
            "recorded_at": _utc_timestamp(recorded_at),
            **sanitized,
            "business_ids": sanitized.get("business_ids", {}),
            "references": sanitized.get("references", []),
            "assertions": sanitized.get("assertions", []),
            "model_calls": sanitized.get("model_calls", []),
            "artifacts": artifact_records,
        }
        _write_json(result_path, step_result)

        failure_path: Path | None = None
        if status == "FAILED":
            failure_path = self.path / "failures" / f"{step_id}.json"
            failure_path.write_bytes(result_path.read_bytes())

        manifest["steps"].append(
            {
                "id": step_id,
                "status": status,
                "result": result_path.relative_to(self.path).as_posix(),
                "failure": failure_path.relative_to(self.path).as_posix() if failure_path else None,
                "sha256": _file_sha256(result_path),
            }
        )
        if status == "FAILED":
            manifest["status"] = "FAILED"
            manifest["completed_at"] = _utc_timestamp(recorded_at)
        _write_json(manifest_path, manifest)
        return result_path

    def complete(
        self,
        *,
        registry_path: Path | None = None,
        now: datetime | None = None,
    ) -> Path:
        from .validation import validate_evidence

        manifest_path = self.path / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "RUNNING":
            raise RuntimeError(f"evidence run is sealed with status {manifest.get('status')}")
        steps = manifest.get("steps")
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("evidence run requires at least one recorded step")
        if any(not isinstance(step, dict) or step.get("status") != "PASSED" for step in steps):
            raise RuntimeError("evidence run contains a non-passing step")

        report = validate_evidence(self.path, registry_path=registry_path)
        if not report.valid:
            raise RuntimeError("evidence validation failed: " + "; ".join(report.errors))

        completed_at = now or datetime.now(timezone.utc)
        manifest["status"] = "COMPLETED"
        manifest["completed_at"] = _utc_timestamp(completed_at)
        _write_json(manifest_path, manifest)
        return manifest_path
