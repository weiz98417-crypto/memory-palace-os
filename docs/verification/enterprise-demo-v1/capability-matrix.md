# 企业能力声明矩阵

> **Status: superseded (历史快照)** — 本文件记录的 ChromaDB / 1536 维 embedding 与旧四层架构描述，已被 ADR-0007（PostgreSQL pgvector 为唯一向量后端）、ADR-0018（Agent 链为景区事件主干）与 ADR-0019（Agent 运行时技术栈）取代。内容仅作历史证据保留，不是当前实现或实施依据。


| 能力 | 声明级别 | 当前状态 | 验证证据 | V1 边界 |
|---|---|---|---|---|
| 确定性演示运行时 | 演示实现 | READY | 四场景实跑、Reset、Docker QA | 固定输入和 Demo Adapter |
| 场景证据与审计 | 已验证 | READY | 步骤证据、attempt、trace、报告 | 不等于生产审计合规认证 |
| 失败恢复 | 已验证 | READY | FAILED attempt 1 + SUCCESS attempt 2 | 固定注入，不是随机外部故障 |
| Play/Pause/Step/Stop/Reset | 已验证 | READY | 单元、集成、浏览器 QA | 单 worker 进程内状态 |
| JSON 报告导出 | 已验证 | READY | 实际浏览器下载并解析 | 本地下载，无签名归档 |
| 真实 LLM | 可选连接 | NOT_CONFIGURED | 环境能力接口 | 默认不读取密钥、不调用模型 |
| PostgreSQL/Redis/ChromaDB | 可选连接 | NOT_CONFIGURED | 连接代码存在 | 不进入默认演示关键路径 |
| 企微/短信/语音 | 演示实现 | RECORDED | Demo Adapter 工具证据 | 不发送真实消息 |
| 正式身份认证和多租户 | 生产扩展位 | PLANNED | 无 | 本地简化鉴权不能公网部署 |
| 高可用与灾备 | 生产扩展位 | PLANNED | 无 | V1 不承诺 |

## 解释规则

- “已验证”只表示本仓库当前自动化或人工验收覆盖了列出的行为。
- “演示实现”表示行为真实存在，但外部副作用由本地适配器记录。
- “可选连接”表示代码或配置扩展位存在，默认未配置。
- “生产扩展位”表示需要独立设计、实施和验收，不能从 Demo 推导已具备。
