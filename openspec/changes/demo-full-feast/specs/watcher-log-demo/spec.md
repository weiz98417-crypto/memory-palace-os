## ADDED Requirements

### Requirement: Watcher log endpoint
`GET /demo/watcher-log` SHALL return recent incident and push log entries combined.

#### Scenario: Query watcher logs
- **WHEN** GET without parameters
- **THEN** returns `{code: 0, data: [{id, type: "incident"|"push", summary, severity, created_at}]}`

#### Scenario: No logs available
- **WHEN** incident_logs and push_logs are both empty
- **THEN** returns `{code: 0, data: []}`

#### Scenario: Database unavailable
- **WHEN** db_client query fails
- **THEN** returns `{code: 1, error: string}` with descriptive message
