"""Create and maintain immutable unified-agent UAT evidence runs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


_RUN_DIRECTORIES = ("api", "artifacts", "failures", "logs", "screenshots", "steps", "traces")
_RUN_JSON_SCAFFOLDS = (
    "browser-console.json",
    "pgvector-retrieval.json",
    "db-assertions.json",
    "evidence-validation.json",
    "llm-calls.json",
    "queue-recovery.json",
)
_BASELINE_TRANSACTION_DIRECTORY = ".uat-baseline.pending"
_RUN_ID_PATTERN = re.compile(r"^UAT-\d{8}T\d{6}Z-[A-Z0-9]{8}$")
_STEP_ID_PATTERN = re.compile(r"^(?:E2E-\d{2}|UAT-F\d{2})$")
_ARTIFACT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "external_ref",
    "password",
    "refresh_token",
    "secret",
    "thumbnail_url",
    "token",
    "access_token",
}
_SOURCE_ROOTS = frozenset({"deploy", "docs", "frontend", "openspec", "scripts", "src", "static", "tests"})
_SOURCE_FILES = frozenset(
    {
        ".dockerignore",
        ".gitignore",
        "CONTEXT.md",
        "main.py",
        "pyproject.toml",
        "requirements.txt",
        "run.sh",
        "uv.lock",
    }
)


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


def _git(repository_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _is_source_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("docs/verification/unified-agent-uat/"):
        return False
    first_part = normalized.split("/", 1)[0]
    return normalized in _SOURCE_FILES or first_part in _SOURCE_ROOTS


def capture_source_fingerprint(repository_root: Path | None = None) -> dict[str, Any]:
    """Capture the exact tracked diff and relevant untracked source without storing content."""

    candidate = (repository_root or Path.cwd()).resolve()
    try:
        root = Path(
            _git(candidate, "rev-parse", "--show-toplevel").stdout.decode("utf-8-sig").strip()
        ).resolve()
        commit = _git(root, "rev-parse", "HEAD").stdout.decode("ascii").strip()
        status_lines = [
            line
            for line in _git(root, "status", "--short", "--untracked-files=all").stdout.decode(
                "utf-8-sig"
            ).splitlines()
            if len(line) > 3 and _is_source_path(line[3:])
        ]
        tracked_diff = _git(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--").stdout
        untracked_paths = [
            path
            for path in _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.decode(
                "utf-8-sig"
            ).split("\0")
            if path and _is_source_path(path)
        ]
        untracked_digest = sha256()
        for relative_path in sorted(untracked_paths):
            source_path = root / relative_path
            if not source_path.is_file():
                continue
            untracked_digest.update(relative_path.replace("\\", "/").encode("utf-8"))
            untracked_digest.update(b"\0")
            untracked_digest.update(bytes.fromhex(_file_sha256(source_path)))
        return {
            "status": "CAPTURED",
            "commit": commit,
            "dirty": bool(status_lines or tracked_diff or untracked_paths),
            "changed_paths": [line[3:].replace("\\", "/") for line in status_lines],
            "tracked_diff_sha256": sha256(tracked_diff).hexdigest(),
            "untracked_source_sha256": untracked_digest.hexdigest(),
        }
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        return {
            "status": "UNAVAILABLE",
            "commit": None,
            "dirty": None,
            "changed_paths": [],
            "tracked_diff_sha256": None,
            "untracked_source_sha256": None,
        }


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
        output_root.mkdir(parents=True, exist_ok=True)
        run_path = output_root / resolved_run_id
        if run_path.exists():
            raise FileExistsError(f"evidence run already exists: {resolved_run_id}")
        staging_path = output_root / f".{resolved_run_id}.{uuid4().hex}.tmp"
        manifest = {
            "schema_version": 1,
            "uat_run_id": resolved_run_id,
            "status": "RUNNING",
            "created_at": _utc_timestamp(created_at),
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
            "source": capture_source_fingerprint(),
            "baseline": None,
            "steps": [],
        }
        scaffold = {
            "schema_version": 1,
            "uat_run_id": resolved_run_id,
            "records": [],
        }
        try:
            staging_path.mkdir(exist_ok=False)
            for directory in _RUN_DIRECTORIES:
                (staging_path / directory).mkdir()
            for name in _RUN_JSON_SCAFFOLDS:
                _write_json(staging_path / name, scaffold)
            (staging_path / "execution-report.md").write_text(
                f"# Unified Agent UAT Execution Report\n\n- `uat_run_id`: `{resolved_run_id}`\n"
                "- Status: RUNNING\n",
                encoding="utf-8",
            )
            _write_json(staging_path / "manifest.json", manifest)
            staging_path.replace(run_path)
        except Exception:
            if staging_path.exists():
                shutil.rmtree(staging_path)
            raise
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

        self._recover_baseline_transaction()
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

    def record_baseline(self, snapshot: Mapping[str, Any]) -> Path:
        """Write the sanitized, immutable pre-journey master-data baseline."""

        sanitized = _redact(deepcopy(dict(snapshot)))
        recovered = self._recover_baseline_transaction()
        manifest_path = self.path / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "RUNNING":
            raise RuntimeError(f"evidence run is sealed with status {manifest.get('status')}")
        baseline_path = self.path / "artifacts" / "uat-baseline.json"
        if manifest.get("baseline") is not None or baseline_path.exists():
            if recovered and _read_json(baseline_path) == sanitized:
                return baseline_path
            raise FileExistsError("UAT baseline already exists")

        transaction_path = self.path / _BASELINE_TRANSACTION_DIRECTORY
        transaction_path.mkdir(exist_ok=False)
        prepared = False
        try:
            staged_baseline = transaction_path / "uat-baseline.json"
            staged_manifest = transaction_path / "manifest.json"
            _write_json(staged_baseline, sanitized)
            manifest["baseline"] = {
                "path": baseline_path.relative_to(self.path).as_posix(),
                "sha256": _file_sha256(staged_baseline),
            }
            _write_json(staged_manifest, manifest)
            _write_json(
                transaction_path / "transaction.json",
                {
                    "schema_version": 1,
                    "baseline_sha256": _file_sha256(staged_baseline),
                    "manifest_sha256": _file_sha256(staged_manifest),
                },
            )
            prepared = True
            staged_baseline.replace(baseline_path)
            staged_manifest.replace(manifest_path)
            shutil.rmtree(transaction_path)
        except Exception:
            if not prepared and transaction_path.exists():
                shutil.rmtree(transaction_path)
            raise
        return baseline_path

    def record_summary(
        self,
        filename: str,
        records: list[Mapping[str, Any]],
    ) -> Path:
        """Append sanitized records to one of the run-level evidence summaries."""

        if filename not in _RUN_JSON_SCAFFOLDS:
            raise ValueError(f"unsupported UAT evidence summary: {filename}")
        if not records or any(not isinstance(record, Mapping) or not record for record in records):
            raise ValueError("evidence summary records must contain non-empty objects")

        self._recover_baseline_transaction()
        manifest = _read_json(self.path / "manifest.json")
        if manifest.get("status") != "RUNNING":
            raise RuntimeError(f"evidence run is sealed with status {manifest.get('status')}")

        summary_path = self.path / filename
        summary = _read_json(summary_path)
        if summary.get("uat_run_id") != self.run_id:
            raise RuntimeError(f"evidence summary run id does not match: {filename}")
        existing_records = summary.get("records")
        if not isinstance(existing_records, list):
            raise RuntimeError(f"evidence summary records are invalid: {filename}")
        sanitized_records = _redact(deepcopy(records))
        _write_json(
            summary_path,
            {
                "schema_version": 1,
                "uat_run_id": self.run_id,
                "records": [*existing_records, *sanitized_records],
            },
        )
        return summary_path

    def _recover_baseline_transaction(self) -> bool:
        transaction_path = self.path / _BASELINE_TRANSACTION_DIRECTORY
        if not transaction_path.exists():
            return False
        if not transaction_path.is_dir() or transaction_path.is_symlink():
            raise RuntimeError("invalid UAT baseline transaction")
        transaction_record_path = transaction_path / "transaction.json"
        if not transaction_record_path.is_file():
            manifest = _read_json(self.path / "manifest.json")
            baseline_path = self.path / "artifacts" / "uat-baseline.json"
            if manifest.get("baseline") is None and not baseline_path.exists():
                shutil.rmtree(transaction_path)
                return False
            raise RuntimeError("incomplete UAT baseline transaction")
        transaction = _read_json(transaction_record_path)
        files = (
            (
                transaction_path / "uat-baseline.json",
                self.path / "artifacts" / "uat-baseline.json",
                transaction.get("baseline_sha256"),
            ),
            (
                transaction_path / "manifest.json",
                self.path / "manifest.json",
                transaction.get("manifest_sha256"),
            ),
        )
        for staged_path, target_path, expected_sha in files:
            if not isinstance(expected_sha, str) or not expected_sha:
                raise RuntimeError("invalid UAT baseline transaction checksum")
            if target_path.is_file() and _file_sha256(target_path) == expected_sha:
                continue
            if not staged_path.is_file() or _file_sha256(staged_path) != expected_sha:
                raise RuntimeError(f"cannot recover UAT baseline transaction: {target_path.name}")
            staged_path.replace(target_path)
        shutil.rmtree(transaction_path)
        return True

    def complete(
        self,
        *,
        registry_path: Path | None = None,
        now: datetime | None = None,
    ) -> Path:
        from .validation import EXPECTED_UAT_STEP_IDS, validate_evidence

        self._recover_baseline_transaction()
        manifest_path = self.path / "manifest.json"
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "RUNNING":
            raise RuntimeError(f"evidence run is sealed with status {manifest.get('status')}")
        steps = manifest.get("steps")
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("evidence run requires at least one recorded step")
        if not isinstance(manifest.get("baseline"), dict):
            raise RuntimeError("evidence run requires a recorded UAT baseline")
        if any(not isinstance(step, dict) or step.get("status") != "PASSED" for step in steps):
            raise RuntimeError("evidence run contains a non-passing step")
        recorded_step_ids = {
            str(step.get("id")) for step in steps if isinstance(step, dict)
        }
        missing_step_ids = [
            step_id for step_id in EXPECTED_UAT_STEP_IDS if step_id not in recorded_step_ids
        ]
        if missing_step_ids:
            raise RuntimeError(
                "evidence run is missing required UAT steps: " + ", ".join(missing_step_ids)
            )

        report = validate_evidence(
            self.path,
            registry_path=registry_path,
            require_complete=True,
        )
        if not report.valid:
            raise RuntimeError("evidence validation failed: " + "; ".join(report.errors))

        completed_at = now or datetime.now(timezone.utc)
        manifest["status"] = "COMPLETED"
        manifest["completed_at"] = _utc_timestamp(completed_at)
        _write_json(manifest_path, manifest)
        return manifest_path
