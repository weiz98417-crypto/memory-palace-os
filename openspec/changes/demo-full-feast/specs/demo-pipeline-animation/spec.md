## ADDED Requirements

### Requirement: Post-hoc pipeline animation
After receiving a pipeline result, the frontend SHALL animate pipeline nodes lighting up sequentially.

#### Scenario: Animate completed pipeline
- **WHEN** `/demo/result/{trace_id}` returns completed result
- **THEN** Stage1 node lights green immediately, Stage2 after 300ms, Router after 600ms, Agent after 900ms

#### Scenario: Pipeline with skipped stage
- **WHEN** ContextTrigger Stage1 excluded the message (bypassed)
- **THEN** Stage1 node shows dim/skipped state, remaining nodes animate as normal

### Requirement: Node state colors
Pipeline nodes SHALL display distinct states: pending(gray), active(blue+pulse), done(green), skipped(dim).

#### Scenario: All stages complete
- **WHEN** full pipeline executes successfully
- **THEN** all four nodes end in done(green) state
