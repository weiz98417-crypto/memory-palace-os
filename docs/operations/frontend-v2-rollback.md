# Frontend V2 rollback runbook

Date: 2026-09-21

## Entries and markers

| App | Public route | V2 marker | Legacy marker |
| --- | --- | --- | --- |
| `console` | `/admin/` | `/admin/assets/index-` | `id="view-dashboard"` |
| `field` | `/assistant/` | `/assistant/assets/index-` | `id="app-screen"` |
| `integration` | `/simulator/wecom/` | `/simulator/wecom/assets/index-` | `/simulator/wecom/app.js` |
| `operations` | `/operations/scenic/` | `/operations/assets/index-` | `/operations/scenic/app.js` |

`/product/` is independent of `FRONTEND_V2_APPS` and remains independently mounted.

## Flag matrix

FRONTEND_V2_APPS defaults to console,field,integration,operations. Empty means all four entries use legacy pages.

| Flag value | V2 entries | Legacy entries |
| --- | --- | --- |
| empty | none | console, field, integration, operations |
| `console` | console | field, integration, operations |
| `field` | field | console, integration, operations |
| `integration` | integration | console, field, operations |
| `operations` | operations | console, field, integration |
| `console,field,integration,operations` | all four | none |

When an entry is enabled, its `static/client/<app>/index.html` must exist. If it is missing, application startup fails instead of silently falling back to legacy.

## Rollback commands

Use the Compose project, env file, and Compose file of the target deployment. The examples below show the scenic demo project:

```powershell
# Roll back console only
$env:FRONTEND_V2_APPS = 'field,integration,operations'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --no-deps --force-recreate app
Remove-Item Env:FRONTEND_V2_APPS

# Roll back field only
$env:FRONTEND_V2_APPS = 'console,integration,operations'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --no-deps --force-recreate app
Remove-Item Env:FRONTEND_V2_APPS

# Roll back integration only
$env:FRONTEND_V2_APPS = 'console,field,operations'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --no-deps --force-recreate app
Remove-Item Env:FRONTEND_V2_APPS

# Roll back operations only
$env:FRONTEND_V2_APPS = 'console,field,integration'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --no-deps --force-recreate app
Remove-Item Env:FRONTEND_V2_APPS
```

Restore V2 for all entries:

```powershell
$env:FRONTEND_V2_APPS = 'console,field,integration,operations'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d --no-deps --force-recreate app
Remove-Item Env:FRONTEND_V2_APPS
```

## Verification

After every switch:

1. Wait for the `app` container to become healthy.
2. Fetch the public route from the host ingress.
3. Confirm the V2 or legacy marker from the table.
4. Check one adjacent entry to prove independence.
5. Keep the route-hit record with release evidence.

The automated drill is:

```powershell
uv run --no-project --with-requirements requirements.txt `
  python scripts/frontend_v2_rollback_drill.py `
  --base-url http://127.0.0.1:8090 `
  --evidence artifacts/frontend-v2/rollback-drill.json
```
