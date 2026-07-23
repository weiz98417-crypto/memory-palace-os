# core-pipeline — 核心消息处理链路

## ADDED Requirements

### Requirement: Database tables exist before startup recovery
The system SHALL execute `init_database()` before attempting `TaskGraph.reload_from_db()` or `PermissionEngine.reload_from_db()` during application startup.

#### Scenario: Fresh start with empty data directory
- **WHEN** the application starts with no existing `data/memory.db`
- **THEN** all tables are created by `init_database()` before any recovery attempt; no "no such table" errors appear in startup logs

#### Scenario: Restart with existing database
- **WHEN** the application starts with an existing `data/memory.db`
- **THEN** `init_database()` runs idempotently (CREATE TABLE IF NOT EXISTS); recovery proceeds without errors

### Requirement: Default route maps to valid agent
The system SHALL return `target_agent: "persona_extract"` from `Orchestrator._default_route()`, which MUST match a registered skill name.

#### Scenario: Unclassified message falls through routing
- **WHEN** a message fails all routing attempts and `_default_route()` is called
- **THEN** the returned route result contains `target_agent` "persona_extract" and `get_skill_by_name("persona_extract")` returns a valid skill instance

### Requirement: Single FastAPI application instance
The system SHALL define only one FastAPI application instance, located in `main.py`. `core/gateway.py` SHALL export router objects only, not a competing `create_app()` function.

#### Scenario: Gateway module exports router only
- **WHEN** `from src.memory_palace.core.gateway import router` is executed
- **THEN** the import succeeds and returns an APIRouter instance; no `create_app` function exists in the module

### Requirement: Skills registered exactly once
The system SHALL call `_auto_register_skills()` only from the application lifespan, not during module import of `skills/__init__.py`.

#### Scenario: Application startup
- **WHEN** the FastAPI application starts
- **THEN** each skill registration log line appears exactly once in the startup logs

### Requirement: No hardcoded external URLs
The system SHALL read external service URLs (push callback, admin callback) from environment variables, falling back to `localhost:8000` when not configured.

#### Scenario: Environment variables not set
- **WHEN** `CONTEXT_TRIGGER_PUSH_URL` and `CONTEXT_TRIGGER_CALLBACK_URL` are not set
- **THEN** a warning is logged with the fallback URL; the system uses `http://localhost:8000` as default

### Requirement: DB path is project-root-relative
The system SHALL resolve `data/memory.db` relative to the project root directory, not the current working directory.

#### Scenario: Application started from different directory
- **WHEN** uvicorn is started from a directory other than the project root
- **THEN** the database file is still located at `<project_root>/data/memory.db`

### Requirement: Demo mode full pipeline
In demo mode (`DEMO_MODE=true`), the system SHALL process a simulated WeChat message through the complete pipeline: decrypt → enqueue → consume → route → execute agent → return result.

#### Scenario: Simulated WeChat message POST
- **WHEN** a POST request is sent to `/webhook/v1/wechat` with demo mode enabled
- **THEN** the message is enqueued, dequeued by the worker, routed through Orchestrator, and a response is returned; a message record exists in the database

#### Scenario: Health check responds ok
- **WHEN** a GET request is sent to `/health`
- **THEN** the response status is 200 with `{"status": "ok"}` and queue depth information
