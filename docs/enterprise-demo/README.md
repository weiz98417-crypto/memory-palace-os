# 企业演示版交付指南

企业演示版是 Memory Palace OS V1 的唯一支持演示入口。它使用 Docker、固定场景数据和 Demo Adapter，在不配置外部密钥的情况下展示多 Agent 协作、步骤证据、失败恢复和报告导出。

## 启动

前置条件：Windows 10/11、Docker Desktop、Docker Compose v2，端口 `8000` 可用。

```powershell
scripts\demo.cmd start
```

启动成功后访问 [http://localhost:8000/demo](http://localhost:8000/demo)。

| 命令 | 行为 |
|---|---|
| `scripts\demo.cmd start` | 构建镜像、启动 Demo、等待健康检查 |
| `scripts\demo.cmd status` | 显示容器、健康状态和端口 |
| `scripts\demo.cmd logs` | 跟随应用日志，按 `Ctrl+C` 退出 |
| `scripts\demo.cmd verify` | 检查服务状态，实跑四个 live API 场景并在一次性容器中运行全量测试 |
| `scripts\demo.cmd reset` | 删除 Demo 数据卷并恢复四场景初始状态 |
| `scripts\demo.cmd stop` | 停止 Demo，不删除数据卷 |

## 推荐演示顺序

1. 展示左侧四个标准场景和企业能力状态。
2. 在 P0 应急场景点击“单步”，说明每一步都有输入、输出、主体、耗时和执行模式。
3. 点击“继续”，再用“暂停”证明动作只在原子步骤边界生效。
4. 完成场景并下载 JSON 运行报告。
5. 切换到任务拆解场景，播放到完成，展示设备检查 attempt 1 失败、attempt 2 恢复及恢复次数。
6. 切换回 P0 场景，证明已完成状态和证据不会被场景切换覆盖。
7. 用顶部 Reset 恢复当前场景，说明只清理演示运行，不操作非演示数据。

## 演示话术边界

- 可以说：默认演示链路是确定性的、可重置的、可审计的。
- 可以说：外部 LLM、企微、短信、PostgreSQL、Redis、ChromaDB 已有扩展位和连接代码。
- 不可以说：默认演示已经调用真实 LLM、发送真实企微/短信、验证生产级高可用或灾备。
- 不可以把 `LOCAL_DEMO_SIMPLIFIED_AUTH` 描述为生产鉴权。

## 交付索引

- [架构与信任边界](architecture.md)
- [关键运行流程](flows.md)
- [权限与访问边界](permissions.md)
- [环境变量与密钥](variables.md)
- [Agent 与自动化边界](automation.md)
- [后台任务](cron.md)
- [测试覆盖图](tests.md)
- [故障处理手册](failure-playbook.md)
- [验证证据](../verification/enterprise-demo-v1/test-results.md)
