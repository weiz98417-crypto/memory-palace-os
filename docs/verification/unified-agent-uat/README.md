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
python -m scripts.unified_agent_uat.cli record --run docs/verification/unified-agent-uat/<uat_run_id> --step E2E-00 --status PASSED --input evidence.json
python -m scripts.unified_agent_uat.cli validate --run docs/verification/unified-agent-uat/<uat_run_id> --registry src/memory_palace/config/feature_registry.yaml
python -m scripts.unified_agent_uat.cli complete --run docs/verification/unified-agent-uat/<uat_run_id>
```

`record` recursively redacts recognized secret fields, writes evidence atomically, calculates SHA-256 checksums, and preserves failed steps under `failures/`. A failed or completed run is sealed; reruns require a new `uat_run_id`.
