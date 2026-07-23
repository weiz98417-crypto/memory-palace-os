# tool-executor — 工具执行器

## ADDED Requirements

### Requirement: Tool executor runs middleware chain
The system SHALL execute tools through a permission-checked middleware chain: register → check permission → execute → audit.

#### Scenario: Registered tool executes with permission check
- **WHEN** `tool_executor.execute("search_memory", args)` is called
- **THEN** the tool's permission level is checked, execution proceeds or is blocked accordingly

#### Scenario: Unregistered tool is rejected
- **WHEN** `tool_executor.execute("unknown_tool", args)` is called
- **THEN** execution is rejected with an error about the tool not being registered

### Requirement: Tool executor is available via Container
`AppContainer` SHALL expose `tool_executor` and `permission_engine` as lazy-loaded properties.

#### Scenario: Container provides tool_executor
- **WHEN** `container.tool_executor` is accessed
- **THEN** a ToolExecutor instance is returned, with permission_engine injected
