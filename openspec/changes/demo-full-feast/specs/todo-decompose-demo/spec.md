## ADDED Requirements

### Requirement: Trigger todo decomposition
`POST /demo/todo/decompose` SHALL queue a task decomposition request through the message pipeline.

#### Scenario: Decompose a goal into tasks
- **WHEN** POST with `{goal: "景区节假日前安全检查"}`
- **THEN** returns `{code: 0, trace_id: string}` and message is queued with `msg_type: "demo_todo_decompose"`

#### Scenario: Orchestrator routes demo_todo_decompose
- **WHEN** orchestrator receives payload with `msg_type == "demo_todo_decompose"`
- **THEN** routes directly to `todo_write` skill, bypassing context_trigger and router

#### Scenario: Result polled from _demo_results
- **WHEN** polling `GET /demo/result/{trace_id}` after decomposition completes
- **THEN** returns `{code: 0, tasks_created: [task_ids], status: "completed"}`

### Requirement: Task dependency tree
The frontend SHALL render tasks with their dependencies as an indented tree structure.

#### Scenario: Render task with dependencies
- **WHEN** TaskGraph contains task A (no deps) and task B (depends on A)
- **THEN** frontend shows task B indented under task A with connecting line indicator
