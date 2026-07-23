# workspace — 工作区隔离

## ADDED Requirements

### Requirement: Workspace prevents path traversal attacks
The WorkspaceManager SHALL reject file paths that attempt to escape the workspace root directory.

#### Scenario: Path traversal detected
- **WHEN** a file operation targets a path containing `..` that would escape the workspace root
- **THEN** the operation is rejected with a ValueError

#### Scenario: Normal path is allowed
- **WHEN** a file operation targets a path within the workspace root
- **THEN** the operation proceeds normally

### Requirement: Workspace available via Container
`AppContainer` SHALL expose `workspace` as a lazy-loaded property.

#### Scenario: Container provides workspace
- **WHEN** `container.workspace` is accessed
- **THEN** a WorkspaceManager instance is returned
