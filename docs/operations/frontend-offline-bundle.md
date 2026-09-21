# Frontend offline release bundle

Date: 2026-09-21

The offline bundle is optional. Source delivery remains canonical; the bundle only supplies the dependency metadata and base images needed to rebuild the V2 frontend without public registry access.

## Bundle contents

`artifacts/frontend-offline-bundle/` contains:

- `source.tar.gz`: the committed source tree used for the build.
- `images/node-image.tar`: the pinned Node base image.
- `images/python-image.tar`: the pinned Python base image used by the normal build.
- `offline-source/offline/node_modules.tar.gz`: Linux dependency graph extracted from the online builder image.
- `offline-source/offline/openapi.json`: OpenAPI metadata exported from the same backend source.
- `manifest.json`: build metadata, file SHA-256 checksums and normalized output checksums.
- `build-transcript.log`: online and offline build transcript.

The bundle never contains frontend `dist`/`static/client` output as the source of delivery. The offline build compiles Vite applications from the source archive.

## Build the bundle online

```powershell
uv run --no-project --with-requirements requirements.txt `
  python scripts/build_frontend_offline_bundle.py `
  --output artifacts/frontend-offline-bundle
```

The script:

1. builds the normal `frontend-builder` target with `--no-cache`;
2. exports the Linux `node_modules` graph and OpenAPI metadata;
3. creates a source archive from the current Git commit;
4. builds `frontend-builder-offline` with `--network=none`;
5. compares online and offline V2 outputs.

## Offline rebuild

```powershell
docker load --input images/node-image.tar
docker load --input images/python-image.tar

docker buildx build `
  --file deploy/Dockerfile `
  --target frontend-builder-offline `
  --network=none `
  --output type=image,name=memory-palace-frontend-offline:latest `
  offline-source
```

The target uses the pinned Node image and the bundled dependency graph. It runs:

```text
node scripts/generate-openapi-types.mjs
vite build for console
vite build for field
vite build for integration
vite build for operations
```

## Online/offline comparison

Raw asset filenames can differ when Vite assigns Vue scoped-style and content hashes on different hosts. The verifier normalizes:

- `/assets/index-<hash>.<ext>` asset names;
- Vue `data-v-<hash>` scope identifiers;
- LF/CRLF line endings.

After normalization, all four `index.html`, JavaScript and CSS outputs must match. `manifest.json` records both raw and normalized hashes.

## Security boundary

- `.env`, secrets, customer data, generated `static/client`, and local model caches are excluded from the source archive and Docker context.
- The bundle contains only committed source, public dependency metadata, base images and OpenAPI contract metadata.
