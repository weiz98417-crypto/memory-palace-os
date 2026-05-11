## ADDED Requirements

### Requirement: Queue maxsize SHALL match settings.yaml

The system SHALL use the queue maxsize value from `settings.yaml` (`storage.pool_size` * 1000 = 10000) in `main.py` instead of the hardcoded 1000. The queue maxsize SHALL be configurable via the `MEMORY_PALACE_QUEUE_MAXSIZE` environment variable.

#### Scenario: Queue uses configured maxsize
- **WHEN** `settings.yaml` specifies `queue_maxsize: 10000` and no env override is set
- **THEN** `asyncio.Queue(maxsize=10000)` is created in `main.py`

#### Scenario: Environment variable overrides config
- **WHEN** `MEMORY_PALACE_QUEUE_MAXSIZE=5000` is set
- **THEN** `asyncio.Queue(maxsize=5000)` is created, overriding the settings.yaml value

### Requirement: Queue full event SHALL be logged and monitored

The system SHALL log a WARNING-level message when `queue.put_nowait()` raises `asyncio.QueueFull`. A metric counter `queue_full_events` SHALL be incremented. The sender SHALL receive a "success" response (fire-and-forget contract preserved) but the metric SHALL be available for monitoring.

#### Scenario: Queue full triggers warning and metric
- **WHEN** the queue is at maxsize and a new message arrives
- **THEN** a WARNING is logged, `queue_full_events` counter is incremented, and "success" is returned to WeChat

### Requirement: Dead-letter queue SHALL be stubbed

The system SHALL add a `dead_letter_queue: list` attribute to `MessageQueueWorker` that stores messages that could not be processed after max retries. The dead-letter queue SHALL be logged on worker shutdown. Full persistence (to disk) is deferred to a follow-up change.

#### Scenario: Message exceeding retry limit goes to dead-letter
- **WHEN** a message fails processing 3 times (max retries)
- **THEN** it is appended to `self._dead_letter_queue` and logged

#### Scenario: Dead-letter queue contents logged on shutdown
- **WHEN** the worker shuts down with items in the dead-letter queue
- **THEN** each dead-lettered message ID is logged at ERROR level
