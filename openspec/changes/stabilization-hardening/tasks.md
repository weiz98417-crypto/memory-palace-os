## 1. LLM Output Sanitization (CRITICAL - blocks all other work)

- [x] 1.1 Create `sanitize_llm_output()` utility in `tools/llm_wrapper.py` with configurable field schema (required keys, types, max lengths, injection token blocklist)
- [x] 1.2 Add sanitization call in `persona_extract/skill.py:_save_persona()` before DB write (spec: llm-output-sanitization S1)
- [x] 1.3 Add sanitization call in `context_trigger/skill.py` stage2 result processing before `write_push_log()` and WeChat push (spec: llm-output-sanitization S2)
- [x] 1.4 Add sanitization call in `todo/skill.py` task decomposition before `task_graph.create_task()` (spec: llm-output-sanitization S3)
- [x] 1.5 Add sanitization call in `tool_executor.py` write_memory path before ChromaDB upsert (spec: llm-output-sanitization S4)
- [x] 1.6 Add sanitization call in `db_client.py:save_confirmed_event()` before vector embedding (spec: llm-output-sanitization S5)
- [x] 1.7 Add sanitization call in `persona_extract/invoke.py` first-person reply before API return (spec: llm-output-sanitization appendix)
- [x] 1.8 Verify: `grep -r "json.dumps|.execute|.upsert" src/` finds no unsanitized LLM output writes

## 2. WeChat Reply Loop (CRITICAL - core functionality gap)

- [x] 2.1 Add `container: AppContainer` parameter to `QueueWorker.__init__()` and store as `self._container`
- [x] 2.2 In `queue_worker._process_message()`, after `dispatch()` returns, read `result.reply_text` and call `self._container.wechat_client.send_text(from_user, reply_text)` if non-empty
- [x] 2.3 Add trace_id correlation in reply log context
- [x] 2.4 Handle `wechat_client.send_text()` exceptions: log error with trace_id, do not retry
- [x] 2.5 Wire container through `main.py` lifespan: pass `app_container` to `QueueWorker(app_container)`
- [ ] 2.6 Verify: send a test message through the full pipeline, confirm reply appears in WeChat

## 3. Queue Configuration Alignment

- [x] 3.1 Read queue maxsize from settings or `MEMORY_PALACE_QUEUE_MAXSIZE` env var in `main.py`, fallback to 10000
- [ ] 3.2 Add `queue_full_events` metric counter in `gateway.py` when `QueueFull` is raised
- [x] 3.3 Stub `dead_letter_queue` in `MessageQueueWorker` with append-on-max-retries logic
- [x] 3.4 Log dead-letter queue contents on worker shutdown
- [x] 3.5 Verify: `grep "maxsize=1000" main.py` returns zero results

## 4. Dead Code Removal

- [x] 4.1 Grep for all references to `ContextManager` and `context` module across `src/`
- [x] 4.2 Delete `src/memory_palace/core/context.py` if no active references found
- [x] 4.3 Disable `_call_summarization_llm()` in `context_tier.py` - convert to no-op with debug log
- [x] 4.4 Delete `tests/unit/test_rate_limiter.py`
- [ ] 4.5 Verify: `pytest tests/ --co` reports zero import errors and no test references to deleted modules

## 5. Test Suite Resurrection

- [ ] 5.1 Fix `test_circuit_breaker.py` - update imports to match current `CircuitBreaker` API, remove skip marker
- [ ] 5.2 Fix `test_hot_reload.py` - update imports after config_manager rename, remove skip marker
- [x] 5.3 Fix `test_orchestrator.py` - update API signatures post lazy-init refactor, remove skip marker (SKIP removed, mocks updated to _save_message, _update_sla_response, persona_extract default route)
- [ ] 5.4 Fix `test_vector_search.py` - update ChromaDB API references, remove skip marker
- [ ] 5.5 Fix `test_wechat_api.py` - resolve httpx fixture conflicts, remove skip marker
- [ ] 5.6 Fix `test_agent_handoff.py` - update wechat_client references, remove skip marker
- [ ] 5.7 Fix `test_memory_retrieval.py` - add mock for CHROMA_OPENAI_API_KEY, remove skip marker
- [ ] 5.8 Fix `test_p0_full_chain.py` - update wechat_client references, remove skip marker
- [ ] 5.9 Verify: `pytest tests/ -v` shows zero SKIP and zero ERROR results

## 6. New Test Coverage

- [ ] 6.1 Create `tests/unit/test_todo_skill.py` - test LLM decomposition, dependency parsing, malformed response handling
- [ ] 6.2 Create `tests/unit/test_file_ops.py` - test read/write/delete within workspace, path traversal rejection
- [ ] 6.3 Create `tests/unit/test_task_graph.py` - test task creation, dependency resolution, status transitions, DB round-trip
- [ ] 6.4 Create `tests/unit/test_tool_executor.py` - test tool registration, execution, permission hooks, listing
- [ ] 6.5 Create `tests/unit/test_context_tier.py` - test warm/cold tiers, budget enforcement, multi-session isolation
- [ ] 6.6 Verify: `pytest tests/ --cov=src/memory_palace --cov-report=term --cov-fail-under=50` passes

## 7. DI Container Unification

- [x] 7.1 Add `container: Optional[AppContainer]` parameter to `Orchestrator.__init__()` (already existed: line 28-32)
- [ ] 7.2 Migrate `orchestrator._save_message()` to use `self._container.db_client` when available
- [ ] 7.3 Migrate `orchestrator._route()` skill resolution to use `self._container` when available
- [ ] 7.4 Add `container` parameter to `gateway.py` message handlers, replace module-level `wx_crypto` with container-provided instance
- [ ] 7.5 Verify: `grep -r "from.*knowledge.db_client import|from.*tools.llm_wrapper import|from.*tools.wechat" src/memory_palace/core/` shows deprecation warnings or zero results

## 8. Final Verification

- [ ] 8.1 Run `pytest tests/ -v` - all tests pass, zero SKIP, zero ERROR
- [x] 8.2 Run `python -c "from main import app"` - app starts without import errors
- [ ] 8.3 Manual smoke test: send test WeChat message, verify reply reaches user
- [ ] 8.4 Run `grep -r "TODO|FIXME" src/memory_palace/ --count` - confirm no regression in TODO count
