## ADDED Requirements

### Requirement: MessageQueueProtocol
系统 SHALL 定义消息队列 Protocol（put, get, task_done, qsize）。

#### Scenario: Protocol compliance
- **WHEN** 任意队列实现遵循该 Protocol
- **THEN** MessageQueueWorker 无需修改即可使用

### Requirement: RedisStreamsQueue
系统 SHALL 提供基于 Redis Streams 的生产级消息队列。

#### Scenario: Message enqueue and dequeue
- **WHEN** 生产者调用 put(message)
- **THEN** 消息通过 XADD 写入 Redis Stream，消费者通过 XREADGROUP 读取

#### Scenario: Dead letter queue
- **WHEN** 消息处理失败超过 3 次
- **THEN** 消息被移入 dead_letter stream

#### Scenario: Message deduplication
- **WHEN** 相同 msg_id 的消息在 60 秒内重复到达
- **THEN** Redis SETEX 检测到重复并丢弃

### Requirement: InMemoryQueue
系统 SHALL 保留 asyncio.Queue 作为 DEMO_MODE 兜底。

#### Scenario: Demo mode uses memory queue
- **WHEN** DEMO_MODE=true
- **THEN** 消息队列使用 InMemoryQueue 实现
