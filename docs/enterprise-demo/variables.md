# 企业演示版环境变量与密钥

| 名称 | 使用方 | 来源 | 敏感 | 风险与约束 |
|---|---|---|---|---|
| `DEMO_PORT` | 本机脚本/Compose | 调用 shell，可选 | 否 | 必须为 1-65535 且未被占用，默认 8000 |
| `PYTHON_BASE_IMAGE` | Docker build | 调用 shell，可选 | 否 | 应固定受信任镜像摘要用于正式发布 |
| `APP_ENV` | 应用 | Compose 固定为 `demo` | 否 | 不能误认为 production |
| `DEMO_MODE` | 应用 | Compose 固定为 `true` | 否 | 关闭后会进入企业连接分支，不属于默认演示 |
| `LOG_LEVEL` | 应用 | Compose | 否 | Debug 可能输出更多上下文，演示默认 INFO |
| `DATABASE_PATH` | SQLite 客户端 | Compose | 否 | 必须位于 Demo 数据卷内 |
| `USE_REDIS` | 队列选择 | Compose 固定为 `false` | 否 | 默认使用进程内队列 |
| `METRICS_ENABLED` | 可观测性 | Compose | 否 | 不等于已接入生产监控平台 |

## 密钥结论

- 默认 Demo Compose 不传入 LLM、企微、短信或数据库密码。
- 前端 HTML 不包含服务端密钥，浏览器只读取场景、环境、运行和报告接口。
- `.env` 不进入默认演示关键路径。

## 生产化前检查

1. 为所有真实渠道使用独立 secret store，不写入 Compose 文件或镜像。
2. 关闭本地简化鉴权，增加用户、租户和资源级权限。
3. 限制反向代理可信来源，不沿用 `--forwarded-allow-ips=*`。
4. 固定基础镜像和 Python 依赖版本并执行供应链扫描。
5. 定义密钥轮换、吊销、审计和泄露响应流程。
