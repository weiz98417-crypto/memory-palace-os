# 企业演示版架构与信任边界

## 产品边界

企业演示版将现有多 Agent 能力包装成一个可控的指挥中心。默认关键路径不依赖互联网、真实消息渠道或企业数据库，所有场景输入和结果均来自版本化 YAML。

## 运行结构

```text
Browser /demo
    |
    | HTTP on 127.0.0.1:8000
    v
FastAPI demo router
    |
    v
ScenarioController
    |-- version conflict guard
    |-- reset > stop > pause boundary priority
    |-- deterministic retry evidence
    v
ScenarioCatalog + Demo Adapter
    |-- scripts/seed_data/demo/*.yaml
    |-- in-process run state
    |-- no real connector initialization
    v
Run snapshot + evidence + JSON report
```

## 技术栈

| 层 | 实现 |
|---|---|
| UI | 单文件原生 HTML/CSS/JavaScript，无 Node 运行时依赖 |
| API | FastAPI + Pydantic |
| 场景控制 | 进程内 `ScenarioController` + `asyncio.Lock` |
| 场景数据 | 版本化 YAML |
| 默认数据 | 只读版本化 YAML + 进程内 run；Docker named volume 预留给后续扩展 |
| 运行 | Gunicorn + Uvicorn worker，非 root 用户 |
| 交付 | Docker Compose + Windows PowerShell/CMD 包装脚本 |

## 信任边界

| 边界 | 当前控制 | 不能推导的结论 |
|---|---|---|
| 浏览器到服务 | 仅绑定 `127.0.0.1`，JSON 契约，运行版本冲突检查 | 不是面向公网的鉴权方案 |
| 场景到工具 | 默认只生成 `DEMO_ADAPTER` 证据，不执行真实外呼 | 不代表真实企微、短信或语音已发送 |
| 服务到数据卷 | 容器以 `appuser` 运行，Demo 卷独立命名 | 不代表多租户 RLS 或生产备份已验证 |
| Agent 到动作 | 动作来自版本化步骤定义，策略结果进入证据 | 不代表任意 LLM 输出可直接调用工具 |
| 企业扩展连接 | 环境能力接口显式显示 `NOT_CONFIGURED` | 不代表 PostgreSQL/Redis/ChromaDB 在默认链路生效 |

## 已知风险与假设

- Demo 路由使用 `LOCAL_DEMO_SIMPLIFIED_AUTH`，只允许本机演示，不应经反向代理暴露到公网。
- 场景运行状态保存在单进程内存中；容器重启后页面标记原 run 为 `INTERRUPTED`，必须由用户 Reset 创建干净运行。
- Gunicorn 固定单 worker，避免同一场景状态在多个进程之间分裂。
- 默认关键路径不读取真实 `.env` 密钥；生产连接必须另行完成权限、密钥轮换和故障演练。
- 邮件和 SEO 不在本项目演示能力范围内，因此不生成对应文档。

## 相关文档

- [关键运行流程](flows.md)
- [权限与访问边界](permissions.md)
- [环境变量与密钥](variables.md)
- [Agent 与自动化边界](automation.md)
- [后台任务](cron.md)
- [测试覆盖图](tests.md)
- [故障处理手册](failure-playbook.md)
- [验证能力矩阵](../verification/enterprise-demo-v1/capability-matrix.md)
