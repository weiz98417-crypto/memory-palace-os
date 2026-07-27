# 后台任务边界

应用启动时会创建队列消费者和 APScheduler，相关实现位于 `main.py`、`core/queue_worker.py` 和 `core/scheduler.py`。

| 任务 | 默认 Demo 依赖 | 失败影响 | 退出控制 |
|---|---|---|---|
| 进程内消息队列消费者 | 否，场景 Controller 不依赖消息入口 | 不影响四个标准场景 | 关机时等待队列排空，取消 consumer task |
| Watcher 定时调度器 | 否 | 不影响演示关键路径 | 关机时调用 scheduler shutdown |

企业演示的确定性来自独立 `ScenarioController`，不依赖 cron 时间、外部队列或后台扫描结果。生产化前应补充作业级幂等键、最后运行状态、重试上限和管理员触发鉴权。
