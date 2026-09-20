"""Failure Replay intake and classification."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

FAILURE_REPLAY_PATH = Path(__file__).with_name("failure_replay_cases.json")
SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token"}
STATUSES = {"RECOVERED", "STILL_FAILING", "INVALID"}


class FailureReplayError(ValueError):
    pass


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def validate_case(case: dict[str, Any]) -> None:
    required = ("id", "source_event_id", "failure_mode", "dataset_version", "source", "redacted_payload")
    missing = [key for key in required if key not in case]
    if missing:
        raise FailureReplayError(f"failure replay case missing fields: {', '.join(missing)}")
    if not str(case["source_event_id"]).strip():
        raise FailureReplayError("failure replay source_event_id is required")
    if not str(case["failure_mode"]).strip():
        raise FailureReplayError("failure replay failure_mode is required")


def classify_replay(case: dict[str, Any], *, current_success: bool) -> str:
    validate_case(case)
    if not str(case.get("source_event_id") or "").strip():
        return "INVALID"
    return "RECOVERED" if current_success else "STILL_FAILING"


def load_failure_replay_cases(path: str | Path | None = None) -> dict[str, Any]:
    fixture_path = Path(path) if path else FAILURE_REPLAY_PATH
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FailureReplayError(f"cannot load failure replay cases: {exc}") from exc
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise FailureReplayError("failure replay cases must be a list")
    ids = set()
    for case in cases:
        validate_case(case)
        if case["id"] in ids:
            raise FailureReplayError(f"duplicate failure replay id: {case['id']}")
        ids.add(case["id"])
        case["redacted_payload"] = redact_payload(case.get("redacted_payload") or {})
    return payload


__all__ = ["FAILURE_REPLAY_PATH", "FailureReplayError", "classify_replay", "load_failure_replay_cases", "redact_payload", "validate_case"]
