# lazy-init — 外部依赖懒加载

## ADDED Requirements

### Requirement: Vector store lazy initialization
The system SHALL NOT instantiate `PalaceVectorStore` at module import time. Instead, calling `get_vector_client()` SHALL return a singleton instance, creating it on first call only.

#### Scenario: Import without env vars
- **WHEN** `from src.memory_palace.knowledge.vector_store import get_vector_client` is executed without `CHROMA_OPENAI_API_KEY` set
- **THEN** no error is raised and no ChromaDB connection is attempted

#### Scenario: First call initializes
- **WHEN** `get_vector_client()` is called for the first time with valid env vars
- **THEN** a `PalaceVectorStore` singleton is created and returned

#### Scenario: Subsequent calls return same instance
- **WHEN** `get_vector_client()` is called multiple times
- **THEN** the same singleton instance is returned each time

### Requirement: Embedding client lazy initialization
The system SHALL NOT detect GPU or load embedding models at module import time. `get_embedding_client()` SHALL perform initialization on first call only.

#### Scenario: Import does not trigger GPU detection
- **WHEN** `from src.memory_palace.tools.embedding_client import get_embedding_client` is executed
- **THEN** no GPU detection, model loading, or device probing occurs

### Requirement: WeChat client lazy initialization
The system SHALL NOT initialize the WeChat API client at module import time. `get_wechat_client()` SHALL return an initialized client, creating it on first call.

#### Scenario: Import without WeChat credentials
- **WHEN** `from src.memory_palace.tools.wechat_client import get_wechat_client` is executed without `WECHAT_CORP_ID` set
- **THEN** a warning is logged but no exception is raised; `get_wechat_client()` returns a mock client on first call

### Requirement: Scheduler delayed initialization
The system SHALL NOT import or instantiate `WatcherSkill` at module level in `core/scheduler.py`. Watcher skill loading SHALL be deferred to `TaskScheduler.start()`.

#### Scenario: Import scheduler without watcher
- **WHEN** `from src.memory_palace.core.scheduler import TaskScheduler` is executed
- **THEN** no WatcherSkill import is attempted; no "WatcherSkill 尚未实现" warning is emitted at import time

#### Scenario: Scheduler starts without serialization error
- **WHEN** `TaskScheduler.start()` is called
- **THEN** cron jobs are registered successfully without "Schedulers cannot be serialized" errors
