## ADDED Requirements

### Requirement: Rate limiting middleware
系统 SHALL 使用 slowapi 对 API 端点实施速率限制。

#### Scenario: Within rate limit
- **WHEN** 客户端在 1 分钟内请求 /api/v1/admin/* 不超过 30 次
- **THEN** 请求正常处理

#### Scenario: Exceed rate limit
- **WHEN** 客户端超过速率限制
- **THEN** 返回 429 Too Many Requests

#### Scenario: Webhook exempt
- **WHEN** 请求路径为 /webhook/*
- **THEN** 不实施速率限制
