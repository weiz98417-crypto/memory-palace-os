## ADDED Requirements

### Requirement: Remove unused ContextManager

The system SHALL delete `src/memory_palace/core/context.py` in its entirety. No active code path references `ContextManager` or its `_store`. All imports of `context` from other modules SHALL be verified as safe to remove before deletion.

#### Scenario: Grep confirms zero references before deletion
- **WHEN** `grep -r "from.*context import ContextManager\|import.*context\.ContextManager" src/` returns zero results
- **THEN** the file is deleted without modification to any other file

#### Scenario: An undiscovered reference is found
- **WHEN** grep finds an active import of ContextManager
- **THEN** that reference is evaluated and either removed or the file is kept with a TODO to migrate

### Requirement: Remove unused ContextCompressor LLM path

The system SHALL remove the LLM summarization call in `context_tier.py` that produces Warm-tier summaries consumed by no agent. The `ContextCompressor` class SHALL be preserved for future use but the `_call_summarization_llm()` method SHALL be converted to a no-op with a log message indicating it is disabled.

#### Scenario: ContextCompressor no longer calls LLM
- **WHEN** `ContextCompressor.compress()` is called
- **THEN** no LLM API call is made; a debug log notes "summarization disabled"

### Requirement: Remove stale test file

The system SHALL delete `tests/unit/test_rate_limiter.py` which imports `src.memory_palace.tools.rate_limiter`, a module that no longer exists.

#### Scenario: Stale test file removed
- **WHEN** `test_rate_limiter.py` is deleted
- **THEN** `pytest` no longer reports an import error for this file
