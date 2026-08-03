# Unified Agent UAT Evidence

This directory stores append-only evidence runs for the unified employee-assistant acceptance journey.

Each run lives under `docs/verification/unified-agent-uat/<uat_run_id>/` and is created before any business journey step. The evidence tooling never creates or mutates business process data. Business state must advance through the formal HTTP or UI interfaces; PostgreSQL, Redis Streams, and ChromaDB are read only for evidence collection.

The WeCom channel for this project is simulator-only:

- accepted entrypoint: `/simulator/wecom/`
- evidence channel mode: `WECOM_SIMULATOR_ONLY`
- real WeCom callbacks and delivery remain disabled
- simulator evidence must never be described as proof that real WeCom is ready

## Commands

```powershell
python -m scripts.unified_agent_uat.cli init
python -m scripts.unified_agent_uat.cli bootstrap --run docs/verification/unified-agent-uat/<uat_run_id>
python -m scripts.unified_agent_uat.cli record --run docs/verification/unified-agent-uat/<uat_run_id> --step E2E-00 --status PASSED --input evidence.json
python -m scripts.unified_agent_uat.cli validate --run docs/verification/unified-agent-uat/<uat_run_id> --registry src/memory_palace/config/feature_registry.yaml
python -m scripts.unified_agent_uat.cli complete --run docs/verification/unified-agent-uat/<uat_run_id>
```

The required order is `init -> bootstrap -> record -> validate -> complete`.

- `init` creates one unique append-only run before any journey data exists.
- `bootstrap` uses only formal management HTTP APIs, refuses a non-empty process baseline, and records `artifacts/uat-baseline.json` plus its SHA-256 in the manifest.
- `record` recursively redacts recognized secret fields, writes evidence atomically, and preserves failed steps under `failures/`.
- `validate` checks architecture, simulator-only channel policy, checksums, baseline process counts, step references, assertions, model truthfulness, and registry evidence rules.
- `complete` requires a recorded baseline and only passing steps before sealing the run.

For the deployed MVP stack, initialize the run locally first and pass it explicitly to the operations command:

```powershell
python -m scripts.unified_agent_uat.cli init
scripts\mvp.cmd bootstrap-uat -EnvFile <path> -UatRun docs\verification\unified-agent-uat\<uat_run_id>
```

The deployment command copies only the selected run into the app container, executes the same formal-API bootstrap command there, and copies the baseline and updated manifest back without overwriting an existing baseline. A failed or completed run is sealed; reruns require a new `uat_run_id`.
