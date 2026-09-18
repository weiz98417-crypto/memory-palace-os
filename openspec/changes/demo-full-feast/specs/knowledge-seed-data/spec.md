## ADDED Requirements

> **Status: superseded (历史快照)** — 本变更记录当时使用的向量后端描述已被 ADR-0007（PostgreSQL pgvector 为唯一向量后端）取代，不再代表当前实现。


### Requirement: Seed data loading
`GET /demo/scenario/switch?name=<name>` SHALL load the specified scenario's seed data.

#### Scenario: Load daily scenario
- **WHEN** GET with `?name=daily`
- **THEN** replaces demo_knowledge ChromaDB collection, inserts personas via db_client, returns `{code: 0, data: {scenario, knowledge_count, persona_count, todo_count}}`

#### Scenario: Load emergency scenario
- **WHEN** GET with `?name=emergency`
- **THEN** replaces all demo data with emergency scenario content

#### Scenario: Invalid scenario name
- **WHEN** GET with `?name=invalid`
- **THEN** returns `{code: 1, error: "unknown scenario"}`

### Requirement: YAML seed data schema
Each scenario YAML SHALL contain knowledge[], personas[], todos[], preset_messages{}.

#### Scenario: Parse daily.yaml
- **WHEN** seed_data.py loads daily.yaml
- **THEN** validates all required fields present and returns structured data

### Requirement: Knowledge search in demo collection
`GET /demo/knowledge/search?q=...&top_k=5` SHALL query the demo_knowledge ChromaDB collection.

#### Scenario: Search with query
- **WHEN** GET with `?q=景区安全&top_k=3`
- **THEN** returns `{code: 0, data: [{content, score, metadata}]}`
