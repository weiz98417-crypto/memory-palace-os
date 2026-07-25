## ADDED Requirements

### Requirement: Multi-model fallback chain
系统 SHALL 支持配置多个 LLM 模型作为 fallback 链。

#### Scenario: Primary model succeeds
- **WHEN** 主模型（DeepSeek）正常响应
- **THEN** 不触发 fallback，直接返回主模型结果

#### Scenario: Primary fails, fallback succeeds
- **WHEN** 主模型 CircuitBreaker 熔断或调用失败
- **THEN** 自动切换到 fallback 模型，成功返回结果

#### Scenario: All models exhausted
- **WHEN** 所有模型均不可用
- **THEN** 抛出 RuntimeError("All models exhausted")

### Requirement: Environment variable configuration
系统 SHALL 通过环境变量配置 fallback 模型。

#### Scenario: Fallback configured
- **WHEN** LLM_FALLBACK_API_KEY 和 LLM_FALLBACK_BASE_URL 均已设置
- **THEN** fallback 链包含主模型和备用模型
