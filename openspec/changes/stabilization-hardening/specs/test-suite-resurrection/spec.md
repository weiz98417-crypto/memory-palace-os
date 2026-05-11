## ADDED Requirements

### Requirement: Fix all SKIP/ERROR tests

The system SHALL restore all 8 SKIP tests and 1 ERROR test to passing status. Each fix SHALL be minimal — update imports, mock signatures, or test fixtures to match current APIs without rewriting test logic.

#### Scenario: test_circuit_breaker unskipped and passing
- **WHEN** `test_circuit_breaker.py` skip marker is removed and imports are updated to match current `CircuitBreaker` API
- **THEN** all tests in the file pass

#### Scenario: test_wechat_api unskipped and passing
- **WHEN** `test_wechat_api.py` skip marker is removed and httpx fixture conflicts are resolved
- **THEN** all tests in the file pass

#### Scenario: test_vector_search unskipped and passing
- **WHEN** `test_vector_search.py` skip marker is removed and ChromaDB API references are updated
- **THEN** all tests in the file pass

#### Scenario: test_orchestrator unskipped and passing
- **WHEN** `test_orchestrator.py` skip marker is removed and API signatures are updated post lazy-init refactor
- **THEN** all tests in the file pass

#### Scenario: All 9 dead tests restored
- **WHEN** all fixes are applied and `pytest tests/` is run
- **THEN** zero SKIP or ERROR results are reported

### Requirement: Add tests for todo skill

The system SHALL add unit tests for `TodoWriteSkill` covering: task decomposition from LLM output, dependency parsing, TaskGraph integration, and error handling for malformed LLM responses.

#### Scenario: Valid LLM decomposition creates tasks
- **WHEN** TodoWrite receives a goal string and LLM returns valid task specs
- **THEN** tasks are created in TaskGraph with correct dependencies

#### Scenario: Malformed LLM response is handled
- **WHEN** TodoWrite LLM returns JSON missing required fields
- **THEN** an error is returned and no tasks are created

### Requirement: Add tests for file_ops

The system SHALL add unit tests for `SafeFileOps` covering: read/write within workspace, path traversal rejection, file listing, and delete operations.

#### Scenario: Path traversal is blocked
- **WHEN** `SafeFileOps.read_file("../../../etc/passwd")` is called
- **THEN** a `PathTraversalError` is raised

#### Scenario: File write within workspace succeeds
- **WHEN** `SafeFileOps.write_file("notes/test.txt", "content")` is called with a valid workspace
- **THEN** the file is written and its path is logged

### Requirement: Add tests for task_graph

The system SHALL add unit tests for `TaskGraph` covering: task creation, dependency resolution, status transitions (PENDING→RUNNING→DONE), failure handling, and DB persistence round-trip.

#### Scenario: Task with dependencies blocks until deps resolve
- **WHEN** Task A depends on Task B, and Task B is not yet DONE
- **THEN** Task A is not returned as "ready to execute"

#### Scenario: Status transition is enforced
- **WHEN** a task in DONE status has `update_status(RUNNING)` called
- **THEN** the transition is rejected with an error

### Requirement: Add tests for tool_executor

The system SHALL add unit tests for `ToolExecutor` covering: tool registration, execution, permission hooks, and multi-tool listing.

#### Scenario: Registered tool is executable
- **WHEN** a tool is registered and `execute_tool("tool_name", {...})` is called
- **THEN** the tool function is invoked with the provided arguments

#### Scenario: Unregistered tool returns error
- **WHEN** `execute_tool("nonexistent", {})` is called
- **THEN** an error is returned indicating the tool is not found

### Requirement: Add tests for context_tier warm/cold tiers

The system SHALL add unit tests for `ContextTier` covering: warm-tier summary generation (when re-enabled), cold-tier narrative archive, budget enforcement, and multi-session isolation.

#### Scenario: Budget enforcement evicts oldest entries
- **WHEN** context entries exceed the configured budget
- **THEN** the oldest entries are evicted and summarized into warm tier

#### Scenario: Multi-session contexts are isolated
- **WHEN** two different sessions store context entries
- **THEN** querying one session does not return entries from the other
