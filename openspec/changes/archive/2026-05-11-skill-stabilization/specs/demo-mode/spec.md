# demo-mode — DEMO_MODE 全链路降级

## ADDED Requirements

### Requirement: LLM calls return mock responses when DEMO_MODE is true
When `DEMO_MODE=true`, `LLMClient.ask()` SHALL return a mock `LLMResponse` without making any network call.

#### Scenario: DEMO_MODE enabled, no API key
- **WHEN** `DEMO_MODE=true` and `OPENAI_API_KEY` is not set
- **THEN** `llm_client.ask()` returns `LLMResponse(content="[DEMO] Mock response", tokens_used=0, model_name="demo")`

#### Scenario: DEMO_MODE disabled, no API key
- **WHEN** `DEMO_MODE` is not "true" and `OPENAI_API_KEY` is not set
- **THEN** `llm_client.ask()` raises `RuntimeError` with message about missing API key

### Requirement: DEMO_MODE does not block non-LLM operations
When `DEMO_MODE=true`, non-LLM operations (DB writes, queue processing, message routing) SHALL execute normally.

#### Scenario: Message processing in DEMO_MODE
- **WHEN** `DEMO_MODE=true` and a WeChat message is received
- **THEN** the message is enqueued, processed through ContextTrigger and Router, and the result is saved to the database
