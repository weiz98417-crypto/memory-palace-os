"""Integrity validation for unified-agent UAT evidence packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


_REQUIRED_DIRECTORIES = ("api", "artifacts", "failures", "logs", "screenshots", "steps", "traces")
_REQUIRED_FILES = (
    "browser-console.json",
    "pgvector-retrieval.json",
    "db-assertions.json",
    "evidence-validation.json",
    "execution-report.md",
    "llm-calls.json",
    "queue-recovery.json",
)
_EXPECTED_ARCHITECTURE = {
    "business_data": "PostgreSQL",
    "queue": "Redis Streams",
    "vector_store": "PostgreSQL pgvector",
    "generative_model": "deepseek-flash",
}
_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "external_ref",
    "password",
    "refresh_token",
    "secret",
    "thumbnail_url",
    "token",
}


@dataclass(frozen=True)
class ValidationReport:
    """The complete, deterministic result of validating one evidence run."""

    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _load_object(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON file {path.as_posix()}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"JSON file must contain an object: {path.as_posix()}")
        return None
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _find_sensitive_fields(value: Any, *, location: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_location = f"{location}.{key}"
            if str(key).lower() in _SENSITIVE_KEYS and item not in (None, "", "<redacted>"):
                findings.append(item_location)
            findings.extend(_find_sensitive_fields(item, location=item_location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_sensitive_fields(item, location=f"{location}[{index}]"))
    return findings


def _resolve_evidence_path(run_path: Path, relative_path: Any, errors: list[str], label: str) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        errors.append(f"{label} path is empty")
        return None
    candidate = (run_path / relative_path).resolve()
    if not candidate.is_relative_to(run_path):
        errors.append(f"{label} path escapes evidence run: {relative_path}")
        return None
    if not candidate.is_file():
        errors.append(f"{label} file is missing: {relative_path}")
        return None
    return candidate


def _resolve_registry_evidence_path(
    run_path: Path,
    *,
    run_id: str,
    evidence_path: Any,
    errors: list[str],
    label: str,
) -> Path | None:
    if not isinstance(evidence_path, str) or not evidence_path.strip():
        errors.append(f"{label} path is empty")
        return None
    normalized = evidence_path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        errors.append(f"{label} path escapes evidence run: {evidence_path}")
        return None
    if run_id in parts:
        parts = parts[parts.index(run_id) + 1 :]
    if not parts:
        errors.append(f"{label} path does not identify a file: {evidence_path}")
        return None
    return _resolve_evidence_path(run_path, PurePosixPath(*parts).as_posix(), errors, label)


def _validate_step(run_path: Path, run_id: str, entry: Any, errors: list[str]) -> None:
    if not isinstance(entry, dict):
        errors.append("manifest step entry must be an object")
        return
    step_id = entry.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        errors.append("manifest step id is empty")
        return
    result_path = _resolve_evidence_path(run_path, entry.get("result"), errors, f"step {step_id}")
    if result_path is None:
        return
    expected_sha = entry.get("sha256")
    if expected_sha != _sha256(result_path):
        errors.append(f"step {step_id} checksum does not match")

    result = _load_object(result_path, errors)
    if result is None:
        return
    if result.get("uat_run_id") != run_id:
        errors.append(f"step {step_id} has an empty or mismatched uat_run_id")
    if result.get("step_id") != step_id:
        errors.append(f"step {step_id} result id does not match")
    status = entry.get("status")
    if result.get("status") != status:
        errors.append(f"step {step_id} status does not match manifest")

    business_ids = result.get("business_ids")
    if not isinstance(business_ids, dict):
        errors.append(f"step {step_id} business_ids must be an object")
    elif any(not isinstance(value, str) or not value.strip() for value in business_ids.values()):
        errors.append(f"step {step_id} contains an empty business id")

    references = result.get("references")
    if status == "PASSED" and (
        not isinstance(references, list)
        or not references
        or any(not isinstance(reference, str) or not reference.strip() for reference in references)
    ):
        errors.append(f"step {step_id} PASSED without non-empty references")

    assertions = result.get("assertions")
    if status == "PASSED" and (
        not isinstance(assertions, list)
        or not assertions
        or any(not isinstance(assertion, dict) or assertion.get("passed") is not True for assertion in assertions)
    ):
        errors.append(f"step {step_id} PASSED without passing assertions")

    model_calls = result.get("model_calls", [])
    if not isinstance(model_calls, list):
        errors.append(f"step {step_id} model_calls must be a list")
    else:
        for call in model_calls:
            if not isinstance(call, dict):
                errors.append(f"step {step_id} model call must be an object")
                continue
            if call.get("model") != "deepseek-flash" or call.get("is_mock") is not False:
                errors.append(f"step {step_id} contains a mock or unsupported model call")

    artifacts = result.get("artifacts", [])
    if not isinstance(artifacts, list):
        errors.append(f"step {step_id} artifacts must be a list")
        return
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append(f"step {step_id} artifact entry must be an object")
            continue
        artifact_path = _resolve_evidence_path(
            run_path,
            artifact.get("path"),
            errors,
            f"step {step_id} artifact",
        )
        if artifact_path is not None and artifact.get("sha256") != _sha256(artifact_path):
            errors.append(f"step {step_id} artifact checksum does not match: {artifact.get('path')}")


def _validate_registry(
    registry_path: Path,
    *,
    run_path: Path,
    run_id: str,
    passed_steps: set[str],
    errors: list[str],
) -> None:
    try:
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"invalid feature registry: {exc}")
        return
    if not isinstance(registry, dict) or not isinstance(registry.get("uat_journeys"), list):
        errors.append("feature registry has no uat_journeys list")
        return
    for journey in registry["uat_journeys"]:
        if not isinstance(journey, dict) or journey.get("status") != "READY":
            continue
        journey_id = journey.get("id")
        evidence = journey.get("evidence")
        resolved_evidence: set[Path] = set()
        if isinstance(evidence, list):
            for evidence_path in evidence:
                resolved = _resolve_registry_evidence_path(
                    run_path=run_path,
                    run_id=run_id,
                    evidence_path=evidence_path,
                    errors=errors,
                    label=f"journey {journey_id} registry evidence",
                )
                if resolved is not None:
                    resolved_evidence.add(resolved)
        expected_step = (run_path / "steps" / f"{journey_id}.json").resolve()
        has_current_evidence = (
            isinstance(journey_id, str)
            and journey_id in passed_steps
            and expected_step in resolved_evidence
        )
        if not has_current_evidence:
            errors.append(f"journey {journey_id} is READY without current-run evidence")


def _validate_baseline(run_path: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    baseline = manifest.get("baseline")
    if baseline is None:
        errors.append("UAT baseline is missing")
        return
    if not isinstance(baseline, dict):
        errors.append("manifest baseline must be an object")
        return
    baseline_path = _resolve_evidence_path(
        run_path,
        baseline.get("path"),
        errors,
        "UAT baseline",
    )
    if baseline_path is None:
        return
    if baseline.get("sha256") != _sha256(baseline_path):
        errors.append("UAT baseline checksum does not match")
    snapshot = _load_object(baseline_path, errors)
    if snapshot is None:
        return
    channel = snapshot.get("channel")
    if channel != {
        "mode": "WECOM_SIMULATOR_ONLY",
        "identity_channel": "WECOM_SIMULATOR",
        "real_wecom_enabled": False,
    }:
        errors.append("UAT baseline channel is not simulator-only")
    process_counts = snapshot.get("process_counts")
    if not isinstance(process_counts, dict) or not process_counts:
        errors.append("UAT baseline has no process counts")
    elif any(not isinstance(value, int) or value != 0 for value in process_counts.values()):
        errors.append("UAT baseline contains business process data")


def _validate_sensitive_fields(run_path: Path, errors: list[str]) -> None:
    for path in sorted(run_path.rglob("*.json")):
        value = _load_object(path, errors)
        if value is None:
            continue
        for location in _find_sensitive_fields(value):
            relative_path = path.relative_to(run_path).as_posix()
            errors.append(f"sensitive field is not redacted in {relative_path}: {location}")


def validate_evidence(run_directory: Path, *, registry_path: Path | None = None) -> ValidationReport:
    """Validate one run without changing evidence or registry state."""

    run_path = run_directory.resolve()
    errors: list[str] = []
    if not run_path.is_dir():
        return ValidationReport((f"evidence run directory is missing: {run_path.as_posix()}",))

    for directory in _REQUIRED_DIRECTORIES:
        if not (run_path / directory).is_dir():
            errors.append(f"required evidence directory is missing: {directory}")
    for filename in _REQUIRED_FILES:
        if not (run_path / filename).is_file():
            errors.append(f"required evidence file is missing: {filename}")

    manifest_path = run_path / "manifest.json"
    manifest = _load_object(manifest_path, errors) if manifest_path.is_file() else None
    if manifest is None:
        if not manifest_path.is_file():
            errors.append("required evidence file is missing: manifest.json")
        return ValidationReport(tuple(errors))

    run_id = manifest.get("uat_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("manifest uat_run_id is empty")
        run_id = ""
    elif run_id != run_path.name:
        errors.append("manifest uat_run_id does not match directory name")
    if manifest.get("architecture") != _EXPECTED_ARCHITECTURE:
        errors.append("manifest architecture does not match the frozen UAT baseline")
    channel = manifest.get("channel")
    if not isinstance(channel, dict) or channel.get("mode") != "WECOM_SIMULATOR_ONLY" or channel.get(
        "real_wecom_enabled"
    ) is not False:
        errors.append("manifest channel must remain WECOM_SIMULATOR_ONLY with real WeCom disabled")
    _validate_baseline(run_path, manifest, errors)

    steps = manifest.get("steps")
    passed_steps: set[str] = set()
    if not isinstance(steps, list):
        errors.append("manifest steps must be a list")
    else:
        seen: set[str] = set()
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("id"), str):
                if step["id"] in seen:
                    errors.append(f"manifest contains duplicate step: {step['id']}")
                seen.add(step["id"])
                if step.get("status") == "PASSED":
                    passed_steps.add(step["id"])
            _validate_step(run_path, run_id, step, errors)

    _validate_sensitive_fields(run_path, errors)
    if registry_path is not None:
        _validate_registry(
            registry_path,
            run_path=run_path,
            run_id=run_id,
            passed_steps=passed_steps,
            errors=errors,
        )
    return ValidationReport(tuple(errors))
