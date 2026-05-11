## Context

Memory Palace OS is a WeChat-bot-based scenic area operations system with 8 registered AI agent skills. The codebase is at ~14,000 lines Python, with significant uncommitted changes from 5 archived openspec changes that were implemented but never fully tested or integrated. Three independent reviews (code review, CEO review, engineering review) converged on the same finding: the foundation has cracks that will compound if not addressed now.

Current state:
- Core message pipeline works (receive → queue → route → agent) but the reply path is incomplete
- 6 LLM trust-boundary vulnerabilities exist at the output→storage junctions
- DI container (`AppContainer`) exists but only ~20% of code uses it
- 42% of tests are dead (SKIP/ERROR) due to API drift from refactors
- `context.py` (250 lines) and `context_tier.py` hot path are dead code
- Single `asyncio.Queue` with mismatched maxsize, no dead-letter queue
- `persona_extract` Q4→Q5 loop bounds bug already fixed in this session

## Goals / Non-Goals

**Goals:**
- Eliminate all stored prompt injection vectors by adding LLM output validation at every DB/vector write point
- Complete the message reply loop so agent responses reach WeChat users
- Remove dead code paths that create confusion and maintenance burden
- Unify dependency injection to eliminate module-level globals and inline lazy imports
- Restore test suite to full signal: fix all SKIP/ERROR tests, add coverage for 5 untested modules
- Align queue configuration with settings

**Non-Goals:**
- Adding new features or skills
- Changing the skill registration/execution model
- Database migration or schema changes
- Performance optimization beyond fixing the queue size mismatch
- UI/frontend changes
- Production deployment configuration

## Decisions

### D1: LLM Output Sanitization Strategy

**Decision**: Add a centralized `sanitize_llm_output()` utility in `tools/llm_wrapper.py` and apply it at every DB/vector write point.

**Rationale**: Each of the 6 CRITICAL findings follows the same pattern — LLM-generated JSON is accepted without shape, type, or content validation before storage. A centralized sanitizer with per-field schemas is more maintainable than 6 ad-hoc validations. The function validates: (1) required keys present, (2) types match schema, (3) string fields ≤ max length, (4) no control characters or injection tokens.

**Alternatives considered**:
- Per-skill validation: each skill validates its own LLM output. Rejected — duplicates logic across 6 files, easy to miss new write points.
- Pydantic models for all LLM output: would work but requires importing pydantic models into every skill. Over-engineered for the current need.

### D2: Reply Path Architecture

**Decision**: Add `send_reply()` call in `queue_worker._process_message()` after orchestrator dispatch returns. Pass `wechat_client` via the DI container.

**Rationale**: The queue worker is the natural reply point — it has the user context (`from_user`) and the agent result. Using the container avoids creating a new dependency chain. The gateway's fire-and-forget pattern (return "success" immediately) is preserved.

**Flow after fix**:
```
queue_worker._process_message()
  → orchestrator.dispatch(message) → returns result with reply_text + from_user
  → if result.reply_text:
      container.wechat_client.send_text(from_user, reply_text)
```

### D3: Dead Code Removal Scope

**Decision**: Remove `context.py` (entire file) and the `context_tier.py` LLM-summary hot path (keep the class but remove the unused summarization call). Delete `test_rate_limiter.py`.

**Rationale**: `context.py`/`ContextManager` is 250 lines with no callers. `context_tier.py` calls LLM for summaries that no agent consumes — it burns tokens for zero value. Removing both eliminates confusion and reduces token costs. The class signatures are preserved for future use but the runtime paths are cut.

### D4: DI Container Unification Approach

**Decision**: Strangler fig pattern — inject `AppContainer` into `Orchestrator.__init__()` and `QueueWorker.__init__()`, then migrate inline imports one at a time.

**Rationale**: A big-bang DI refactor would touch every file and risk regressions. The strangler fig lets us migrate `db_client`, `llm_wrapper`, and `wechat_client` references incrementally. The container is already instantiated in `main.py` lifespan — it just needs to be threaded through to consumers.

### D5: Test Resurrection Priority

**Decision**: Fix SKIP/ERROR tests first (low effort, high signal recovery), then add tests for uncovered modules (higher effort, essential coverage).

**Priority order**: (1) Unskip tests with trivial fixes (import paths, mock updates), (2) Fix `test_circuit_breaker`, `test_wechat_api`, `test_vector_search` with moderate effort, (3) Add new tests for `todo`, `file_ops`, `task_graph`, `tool_executor`, `context_tier`.

## Risks / Trade-offs

- **[Risk]** Centralized sanitization could be bypassed by new write paths → **Mitigation**: Add a lint rule or pre-commit hook that flags direct `json.dumps()` calls before DB writes
- **[Risk]** Reply path wiring may expose race conditions in concurrent message handling → **Mitigation**: WeChat sends messages sequentially per user; the `asyncio.Semaphore(5)` already gates concurrency
- **[Risk]** Removing `context.py` may break undiscovered import references → **Mitigation**: Grep for `from.*context import|import.*context` before deletion
- **[Risk]** Test unskipping may reveal deeper bugs that were hidden by SKIP → **Mitigation**: Fix tests one file at a time, verify each fix independently
- **[Trade-off]** Strangler fig DI migration means the container and global registry coexist during transition → Acceptable: the transition period is short (this change), no production traffic exists yet

## Open Questions

- Should `wechat_client.send_text()` be async or sync? (current implementation uses `httpx.AsyncClient` — stick with async)
- Should sanitization failures reject the write or log-and-sanitize? (decision: reject hard for type/shape errors, sanitize for string content issues)
