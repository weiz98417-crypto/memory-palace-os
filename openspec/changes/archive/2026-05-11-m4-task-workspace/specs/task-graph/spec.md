# task-graph — 任务依赖图

## ADDED Requirements

### Requirement: TaskGraph recovers pending tasks from database
`TaskGraph.reload_from_db()` SHALL load PENDING and interrupted RUNNING tasks from the `tasks` table at startup.

#### Scenario: Recover pending tasks after restart
- **WHEN** `reload_from_db()` is called and `tasks` table has PENDING entries
- **THEN** those tasks are loaded into the in-memory task graph

#### Scenario: Reset interrupted running tasks
- **WHEN** `reload_from_db()` finds tasks with RUNNING status
- **THEN** those tasks are reset to PENDING status

### Requirement: TaskGraph available via Container
`AppContainer` SHALL expose `task_graph` as a lazy-loaded property.

#### Scenario: Container provides task_graph
- **WHEN** `container.task_graph` is accessed
- **THEN** a TaskGraph instance is returned
