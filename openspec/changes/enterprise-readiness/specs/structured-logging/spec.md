## ADDED Requirements

### Requirement: trace_id propagation
系统 SHALL 使用 contextvars 在整个请求生命周期中传播 trace_id。

#### Scenario: trace_id in every log line
- **WHEN** HTTP 请求到达并设置 trace_id
- **THEN** 该请求触发的所有日志条目自动包含相同的 trace_id

### Requirement: JSON log format
系统 SHALL 支持通过 LOG_FORMAT 环境变量切换 JSON 日志格式。

#### Scenario: JSON format enabled
- **WHEN** LOG_FORMAT=json
- **THEN** 每条日志输出为 JSON 对象，包含 timestamp, level, trace_id, module, line, message 字段

#### Scenario: Default format preserved
- **WHEN** LOG_FORMAT 未设置
- **THEN** 日志保持现有 loguru 格式
