# permission-engine — 三级权限引擎

## ADDED Requirements

### Requirement: Tools classified by permission level
The system SHALL classify tools into FREE (direct execution), LOGGED (execution + audit), and APPROVAL (requires admin approval) levels.

#### Scenario: FREE tool executes directly
- **WHEN** a FREE-level tool (e.g., `search_memory`) is invoked
- **THEN** the tool executes without requiring approval or logging

#### Scenario: LOGGED tool writes audit trail
- **WHEN** a LOGGED-level tool (e.g., `write_memory`) is invoked
- **THEN** the tool executes and a record is written to `tool_invocation_logs`

#### Scenario: APPROVAL tool requires admin
- **WHEN** an APPROVAL-level tool (e.g., `send_sms`) is invoked
- **THEN** an approval request is created in `approval_requests` and execution is suspended until approved

### Requirement: Permission engine reloads from database
`PermissionEngine.reload_from_db()` SHALL load pending approval requests from the database at startup.

#### Scenario: Start with pending approvals
- **WHEN** permission engine calls `reload_from_db()` and `approval_requests` table has PENDING entries
- **THEN** those entries are loaded into the in-memory pending queue
