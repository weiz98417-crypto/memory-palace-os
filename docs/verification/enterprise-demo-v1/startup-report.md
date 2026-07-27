# Docker 启停与恢复报告

## 验证结果

| 操作 | 初始状态 | 结束条件 | 耗时 |
|---|---|---|---:|
| Stop | 应用 healthy | Demo 容器和网络移除，卷保留 | 1.507 s |
| Cold Start | 无 Demo 容器，镜像与卷存在 | `/health` 返回 ok | 5.219 s |
| Reset | 应用 healthy，旧 Demo 卷存在 | 卷重建、应用 healthy、四场景 IDLE | 4.022 s |

Reset 验证中，`memory-palace-demo-data` 从旧卷删除并重建。最终交付卷创建时间为 `2026-07-27T06:34:00Z`，应用容器健康状态为 `healthy`。

## 隔离确认

所有写操作都通过 `deploy/docker-compose.demo.yml` 和 `memory-palace-demo` Compose project 执行。以下容器在验收前后均保持运行，未执行 stop、restart、remove 或 volume 操作：

- `qiuqiu-master-backend-1`
- `qiuqiu-master-postgres-1`
- `qiuqiu-master-redis-1`

## 命令行为

- Start：构建、后台启动、等待健康检查。
- Status：正确显示 healthy 和 `127.0.0.1:8000->8000/tcp`。
- Logs：输出最近 160 行并持续跟随，人工中断不影响容器。
- Verify：四个 live API 场景和 176 条测试通过，临时测试容器自动退出和删除。
- Reset：删除并重建唯一 Demo 卷。
- Stop：保留数据卷。
