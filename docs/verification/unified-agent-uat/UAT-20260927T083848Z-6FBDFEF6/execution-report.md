# Unified Agent UAT Execution Report

- `uat_run_id`: `UAT-20260927T083848Z-6FBDFEF6`
- Status: COMPLETED
- Result: 30/30 required journeys PASSED; the feature registry points all 30 READY entries to this run.
- Environment: isolated `memory-palace-uat-clean6` Docker Compose stack, PostgreSQL, Redis Streams, pgvector, TEI bge-m3, and real DeepSeek `deepseek-flash` calls.
- Recovery evidence: App and interview restarts, Redis pending → claim → ACK, TEI outage and recovery for search and publication, concurrent approval with a failed delivery, and DeepSeek 401/timeout with a same-key retry after restoring the real endpoint.
- Model substitution: only the E2E-15 Router/MemoryOps/Persona decision envelope and E2E-16 observation envelope use the declared high-fidelity test double; published-card retrieval, identity, feedback, queue, and container recovery are real operations.
- DeepSeek circuit evidence: UAT-F03 records the `llm_call_logs` diagnostic entering OPEN after three failures and closing after a successful retry. It does not assert that TodoWrite itself rejected a request because of an open circuit.
- Verification: complete evidence and registry validation passed; the unit suite and targeted recovery, experience, and controlled-action integration suites passed in the repository-mounted app image. Nineteen PowerShell-only unit cases were skipped on Linux.
