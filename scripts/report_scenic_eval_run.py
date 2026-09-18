"""Report an evaluation run to the API so the operations UI can show it."""

from __future__ import annotations

import argparse
import json
import pathlib
import urllib.error
import urllib.request


def _post(base: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/api/v1/operations/scenic/evaluation-runs",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.headers["Content-Type"] = "application/json"
    request.headers["Authorization"] = "Bearer " + token
    request.headers["Idempotency-Key"] = payload.get("run_id") or "eval-report"
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise SystemExit("report failed: " + str(exc.code) + " " + raw.decode("utf-8", errors="replace")[:300])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tier", required=True, choices=("contract", "deep"))
    parser.add_argument("--case-set", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--context-source", default=None)
    parser.add_argument("--elapsed", type=float, default=None)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    results = json.loads(pathlib.Path(args.results).read_text(encoding="utf-8"))
    summary = json.loads(pathlib.Path(args.summary).read_text(encoding="utf-8")) if args.summary else {}
    payload = {
        "tier": args.tier,
        "case_set": args.case_set,
        "results": results,
        "judge_model": args.judge_model,
        "context_source": args.context_source,
        "elapsed_seconds": args.elapsed,
        "summary": summary,
        "run_id": args.run_id,
    }
    response = _post(args.base, args.token, payload)
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
