# Frontend V2 release observation

Date: 2026-09-21

## Purpose

`F18` removal remains blocked until one release observation window completes and all four gates hold. This runbook defines how that window is measured and how legacy traffic is detected.

## Gate conditions

| Gate | Evidence |
| --- | --- |
| One release window | A Git tag newer than the cutover commit `6bd36f68e2c10a6d546bf516c316935ca00c432b` |
| Functional / visual acceptance | F11–F14 sign-off and browser evidence |
| Rollback | `artifacts/frontend-v2/rollback-drill.json` passes |
| Zero legacy traffic | No requests to legacy-only assets during the observation window |

Legacy-only asset patterns:

```text
/assistant/app.js
/simulator/wecom/app.js
/operations/scenic/app.js
/shared/client.js
```

Public HTML routes use the same paths for V2 and legacy, so the legacy-only assets are the observable rollback signal.

## Commands

Start the ledger:

```powershell
uv run --no-project --with-requirements requirements.txt `
  python scripts/frontend_v2_observation.py start `
  --start-commit 6bd36f68e2c10a6d546bf516c316935ca00c432b
```

Collect a sample:

```powershell
uv run --no-project --with-requirements requirements.txt `
  python scripts/frontend_v2_observation.py collect
```

Inspect status:

```powershell
uv run --no-project --with-requirements requirements.txt `
  python scripts/frontend_v2_observation.py status
```

Each collection checks:

- the current `FRONTEND_V2_APPS` value;
- all four public routes return the V2 marker;
- requests to legacy-only assets since the previous sample;
- whether a release tag newer than the cutover commit exists.

The collector exits non-zero on legacy hits, route failure or window completion so the scheduled observation job can notify without claiming F18 done.
