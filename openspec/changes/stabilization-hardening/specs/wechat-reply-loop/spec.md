## ADDED Requirements

### Requirement: Orchestrator output SHALL be sent to WeChat user

The system SHALL take the `reply_text` field from the agent's `SkillOutput` and send it to the original WeChat user via `wechat_client.send_text()`. The reply SHALL be sent after the orchestrator's `dispatch()` completes successfully. If `reply_text` is `None` or empty, no reply SHALL be sent.

#### Scenario: Agent produces reply text that reaches the user
- **WHEN** orchestrator dispatches a message and the agent returns `SkillOutput(success=True, reply_text="已收到您的报告，正在处理")`
- **THEN** `wechat_client.send_text(from_user, "已收到您的报告，正在处理")` is called with the original user's ID

#### Scenario: Agent returns empty reply text — no message sent
- **WHEN** orchestrator dispatches a message and the agent returns `SkillOutput(success=True, reply_text=None)`
- **THEN** no WeChat message is sent and no error is logged

#### Scenario: WeChat send fails — error is logged and surfaced
- **WHEN** `wechat_client.send_text()` raises an exception (network timeout, API error)
- **THEN** the error is logged with trace_id and the message is NOT retried (WeChat handles retry at the protocol level)

### Requirement: Reply path SHALL use DI container for wechat_client

The system SHALL obtain the `wechat_client` instance from `AppContainer` rather than through inline imports. The QueueWorker SHALL accept `container: AppContainer` in its constructor and pass it through to the reply logic.

#### Scenario: QueueWorker receives container at construction
- **WHEN** QueueWorker is instantiated with `container=app_container`
- **THEN** `self._container.wechat_client` is available for sending replies

#### Scenario: QueueWorker without container logs warning
- **WHEN** QueueWorker is instantiated without a container (legacy path)
- **THEN** a warning is logged and reply sending is silently skipped (graceful degradation)

### Requirement: Reply SHALL include trace correlation

The system SHALL include the original message's `trace_id` in the reply's log context and optionally append it to the WeChat message for debugging. In production mode, trace IDs SHALL NOT be visible to users.

#### Scenario: Trace ID logged with reply
- **WHEN** a reply is sent to a WeChat user
- **THEN** the log entry includes both the received message's trace_id and the reply action
