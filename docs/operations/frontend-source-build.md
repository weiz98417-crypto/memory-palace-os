# Frontend source-package build

The source package builds the V2 frontend inside the application image. A host-side `pnpm build` is not required before Docker build.

## Build

From the repository root:

```powershell
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml build app
```

The frontend builder stage:

1. uses the pinned Node `24.15.0` image;
2. installs pnpm `11.19.0` and runs `pnpm install --frozen-lockfile`;
3. exports the real FastAPI OpenAPI document from the Python source;
4. runs the OpenAPI type check against that document;
5. builds `console`, `field`, `integration`, and `operations`;
6. verifies that all four `index.html` files exist.

The runtime image contains the generated output under:

```text
/app/static/client/console
/app/static/client/field
/app/static/client/integration
/app/static/client/operations
```

## Registry override

The default Node base image is:

```text
node:24.15.0-bookworm-slim
```

For registries or mirrors, override Node and npm without changing the source:

```powershell
$env:NODE_IMAGE = 'registry.example.com/library/node:24.15.0-bookworm-slim'
$env:NPM_REGISTRY = 'https://registry.example.com/npm/'
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml build app
```

`FRONTEND_V2_APPS` is passed through to the application container by Compose. Selecting an entry only changes which static app is mounted; it does not change the build.

## Rollout boundary

Building the V2 assets does not switch any entry. Runtime selection still uses:

```text
FRONTEND_V2_APPS=
```

V2 remains disabled until an entry passes the functional and visual acceptance gates in the frontend migration tickets.
