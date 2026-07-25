## ADDED Requirements

### Requirement: Secrets validation at startup
系统 SHALL 在启动时校验所有必需的密钥已设置。

#### Scenario: All secrets present
- **WHEN** 所有必需环境变量均已设置
- **THEN** 启动继续，无警告

#### Scenario: Missing required secret
- **WHEN** DATABASE_URL 或 LLM_PRIMARY_API_KEY 未设置且非 DEMO_MODE
- **THEN** 启动时打印缺失密钥列表并退出（fail-fast）

#### Scenario: Demo mode skips validation
- **WHEN** DEMO_MODE=true
- **THEN** 跳过密钥校验，使用安全默认值
