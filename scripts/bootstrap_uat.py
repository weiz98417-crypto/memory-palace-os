"""Compatibility wrapper for the evidence-aware UAT bootstrap command."""

from __future__ import annotations

import sys

from scripts.unified_agent_uat.cli import main as evidence_cli_main


def main() -> int:
    return evidence_cli_main(["bootstrap", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
