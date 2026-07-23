# agent-memory — Agent 内存隔离

## ADDED Requirements

### Requirement: AgentMemory provides scoped context per agent
`AgentMemory.build_scoped_context()` SHALL return a context dict containing only the fields relevant to the specified agent.

#### Scenario: Router gets minimal context
- **WHEN** `build_scoped_context(agent_name="router", session_id="s1", base_context=ctx)` is called
- **THEN** the returned dict contains only `raw_text` and `msg_id`

#### Scenario: Commander gets full context
- **WHEN** `build_scoped_context(agent_name="commander", session_id="s1", base_context=ctx)` is called
- **THEN** the returned dict contains `raw_text`, `severity`, `from_user`, `msg_id`

#### Scenario: Unknown agent gets all fields
- **WHEN** `build_scoped_context(agent_name="unknown_agent", session_id="s1", base_context=ctx)` is called
- **THEN** the returned dict contains all available fields from base_context

### Requirement: AgentMemory records per-agent conversation turns
`AgentMemory.record_agent_turn()` SHALL store a conversation turn associated with a specific agent and session.

#### Scenario: Record and retrieve turns
- **WHEN** `record_agent_turn(session_id="s1", agent_name="router", input_text="hello", output_text="hi")` is called
- **THEN** the turn is stored and can be retrieved for session `s1` and agent `router`

### Requirement: AgentMemory prevents cross-agent information leak
Agent turns recorded for one agent SHALL NOT appear in another agent's context.

#### Scenario: Router cannot see Commander turns
- **WHEN** Router turns and Commander turns exist for the same session
- **THEN** `build_scoped_context(agent_name="router", ...)` does not include Commander's conversation history
