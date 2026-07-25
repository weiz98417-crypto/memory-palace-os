## ADDED Requirements

### Requirement: API Key authentication
系统 SHALL 通过 `X-API-Key` 请求头验证 API 密钥。

#### Scenario: Valid API key
- **WHEN** 请求携带 `X-API-Key: valid-key`
- **THEN** 认证通过，请求正常处理

#### Scenario: Invalid API key
- **WHEN** 请求携带无效的 API key
- **THEN** 返回 401 Unauthorized

#### Scenario: Demo mode bypass
- **WHEN** DEMO_MODE=true
- **THEN** 所有认证检查自动通过

### Requirement: JWT authentication
系统 SHALL 支持 Bearer Token JWT 认证。

#### Scenario: Valid JWT
- **WHEN** 请求携带 `Authorization: Bearer <valid-jwt>`
- **THEN** JWT 验证通过，请求正常处理
