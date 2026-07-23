# context-tier — 三层上下文压缩

## ADDED Requirements

### Requirement: ContextTier builds three-tier context
`ContextTier.build_tiered_context()` SHALL return a dict with `hot`, `warm`, and `cold` keys representing Hot/Warm/Cold tier messages.

#### Scenario: Hot tier retains recent messages
- **WHEN** `build_tiered_context()` is called with 25 messages and hot_count=10
- **THEN** the `hot` list contains the 10 most recent messages with full content

#### Scenario: Warm tier is empty when no compression configured
- **WHEN** `build_tiered_context()` is called and LLM summarization is not configured
- **THEN** the `warm` list is empty

#### Scenario: Cold tier is empty when no compression configured
- **WHEN** `build_tiered_context()` is called and LLM summarization is not configured
- **THEN** the `cold` list is empty

### Requirement: ContextTier total context respects budget
The combined context from all three tiers SHALL respect the configured total message budget.

#### Scenario: Budget limits total messages
- **WHEN** `build_tiered_context()` is called with 100 messages and total_budget=30
- **THEN** the sum of hot + warm + cold message counts does not exceed 30
