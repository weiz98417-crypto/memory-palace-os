## ADDED Requirements

### Requirement: Orchestrator SHALL accept and use AppContainer

The system SHALL inject `AppContainer` into `Orchestrator.__init__()` as an optional parameter. When provided, the orchestrator SHALL use container-provided clients (`db_client`, `llm_client`, `wechat_client`) instead of inline lazy imports. When not provided (legacy path), the orchestrator SHALL fall back to existing behavior with a deprecation warning.

#### Scenario: Orchestrator uses container for DB operations
- **WHEN** Orchestrator is instantiated with `container=app_container` and calls `_save_message()`
- **THEN** it uses `self._container.db_client.execute()` instead of inline `from ...knowledge.db_client import ...`

#### Scenario: Orchestrator falls back without container
- **WHEN** Orchestrator is instantiated without a container
- **THEN** a deprecation warning is logged and inline imports are used

### Requirement: QueueWorker SHALL accept and thread AppContainer

The system SHALL inject `AppContainer` into `QueueWorker.__init__()` and thread it through to `Orchestrator` on construction. The container SHALL be created once in `main.py` lifespan and passed to both Gateway and QueueWorker.

#### Scenario: Container flows from main to orchestrator
- **WHEN** `main.py` lifespan creates AppContainer, passes it to QueueWorker, which passes it to Orchestrator
- **THEN** all three components share the same container instance and its cached resources

### Requirement: Gateway SHALL use container for wechat_crypto and wechat_client

The system SHALL replace the module-level `wx_crypto` singleton in `gateway.py` with container-provided instances. The gateway SHALL accept `container: AppContainer` as an optional parameter.

#### Scenario: Gateway decrypts message using container-provided crypto
- **WHEN** a WeChat message arrives and gateway has a container
- **THEN** decryption uses `self._container.wechat_crypto` instead of the module-level global
