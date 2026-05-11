## Why

The codebase has accumulated significant structural debt across three dimensions: (1) 6 CRITICAL LLM trust-boundary vulnerabilities where LLM-generated data is stored without sanitization, creating stored prompt injection vectors; (2) the core message reply loop is incomplete — the orchestrator produces `SkillOutput.reply_text` but no code sends it back to WeChat users; (3) 42% of tests are dead (8 SKIP, 1 ERROR) due to API drift, and 5 new modules have zero test coverage. The project skeleton is solid but unreliable in its current state. Stabilization now prevents compounding breakage as more features stack on a cracked foundation.

## What Changes

- **Fix 6 LLM trust-boundary vulnerabilities**: Add output schema validation, sanitization, and length limits at every point where LLM-generated data is written to DB or vector store
- **Wire the WeChat reply path**: Connect orchestrator output to `wechat_client.send()` so agent replies actually reach users
- **Remove dead code**: Delete `context.py`/`ContextManager` (unused), `context_tier.py`/`ContextCompressor` (LLM summaries never consumed), and stale test `test_rate_limiter.py`
- **Unify DI container usage**: Replace inline lazy imports in orchestrator, gateway, and skills with `AppContainer` injection
- **Resurrect the test suite**: Fix 8 SKIP tests and revive circuit_breaker, wechat_client, vector_store coverage; add tests for todo, file_ops, task_graph, tool_executor
- **Fix queue size mismatch**: Align `main.py` queue maxsize with `settings.yaml` (1000 → 10000)
- **Already fixed**: `persona_extract/skill.py` Q4→Q5 loop bounds bug (previously applied)

## Capabilities

### New Capabilities

- `llm-output-sanitization`: Validate and sanitize all LLM-generated data before DB/vector store writes. Covers persona_extract, context_trigger, tool_executor, todo, db_client, and persona_extract invoke paths.
- `wechat-reply-loop`: Complete the message round-trip: WeChat message → gateway → queue → orchestrator → agent → reply_text → wechat_client.send() → user.
- `di-container-unification`: Standardize dependency injection across orchestrator, gateway, queue_worker, and skills to use AppContainer instead of module-level globals and inline lazy imports.
- `dead-code-removal`: Remove context.py/ContextManager, context_tier.py/ContextCompressor hot path, and stale test files referencing deleted modules.
- `test-suite-resurrection`: Fix 8 SKIP/ERROR tests, add coverage for todo, file_ops, task_graph, tool_executor, context_tier warm/cold tiers.
- `queue-config-alignment`: Align queue maxsize between main.py (1000) and settings.yaml (10000), add dead-letter queue implementation.

## Impact

- **Files to modify**: `orchestrator.py`, `gateway.py`, `queue_worker.py`, `main.py`, `persona_extract/skill.py`, `persona_extract/invoke.py`, `context_trigger/skill.py`, `tool_executor.py`, `db_client.py`, `todo/skill.py`, `skills/__init__.py`, `container.py`, `settings.yaml`
- **Files to delete**: `context.py`, `context_tier.py`, `tests/unit/test_rate_limiter.py`
- **Tests to fix**: 8 SKIP/ERROR files
- **Tests to add**: 5 new test files for uncovered modules
- **Breaking changes**: None — all changes are internal stability improvements, no public API changes
