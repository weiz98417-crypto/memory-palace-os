"""Command-line adapter for the unified-agent UAT evidence module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .evidence import EvidenceRun
from .validation import validate_evidence
from src.memory_palace.operations.uat_bootstrap import (
    UATBootstrapConfig,
    UATBootstrapError,
    bootstrap_uat_master_data,
)


DEFAULT_OUTPUT_ROOT = Path("docs/verification/unified-agent-uat")
DEFAULT_REGISTRY_PATH = Path("src/memory_palace/config/feature_registry.yaml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage unified-agent UAT evidence packages")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a new append-only evidence run")
    init.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    init.add_argument("--run-id")

    bootstrap = commands.add_parser(
        "bootstrap",
        help="prepare UAT master data through formal APIs and record its baseline",
    )
    bootstrap.add_argument("--run", type=Path, required=True)

    record = commands.add_parser("record", help="record one sanitized UAT step from a JSON input file")
    record.add_argument("--run", type=Path, required=True)
    record.add_argument("--step", required=True)
    record.add_argument("--status", choices=("PASSED", "FAILED"), required=True)
    record.add_argument("--input", type=Path, required=True)

    validate = commands.add_parser("validate", help="validate an evidence run without modifying it")
    validate.add_argument("--run", type=Path, required=True)
    validate.add_argument("--registry", type=Path)

    complete = commands.add_parser("complete", help="validate and seal an all-passing evidence run")
    complete.add_argument("--run", type=Path, required=True)
    complete.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    return parser


def _open_run(path: Path) -> EvidenceRun:
    return EvidenceRun(path=path.resolve(), run_id=path.resolve().name)


def _emit(value: object, *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False), file=stream or sys.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            run = EvidenceRun.create(args.output_root, run_id=args.run_id)
            _emit({"uat_run_id": run.run_id, "path": str(run.path)})
            return 0
        if args.command == "bootstrap":
            config = UATBootstrapConfig.from_environment()
            result = __import__("asyncio").run(bootstrap_uat_master_data(config))
            baseline_path = _open_run(args.run).record_baseline(result.baseline_snapshot)
            _emit(
                {
                    "uat_run_id": args.run.resolve().name,
                    "baseline": str(baseline_path),
                    "venue_id": result.venue_id,
                    "user_count": result.user_count,
                    "identity_count": result.identity_count,
                }
            )
            return 0
        if args.command == "record":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("step input must contain a JSON object")
            result_path = _open_run(args.run).record_step(args.step, status=args.status, evidence=payload)
            _emit({"recorded": str(result_path)})
            return 0
        if args.command == "validate":
            report = validate_evidence(args.run, registry_path=args.registry)
            _emit({"valid": report.valid, "errors": list(report.errors)})
            return 0 if report.valid else 1
        if args.command == "complete":
            manifest_path = _open_run(args.run).complete(registry_path=args.registry)
            _emit({"completed": str(manifest_path)})
            return 0
    except (
        FileExistsError,
        OSError,
        RuntimeError,
        UATBootstrapError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        _emit({"error": str(exc)}, stream=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
