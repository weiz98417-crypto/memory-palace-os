# 企业演示版关键运行流程

## 启动与健康检查

**参与者：** 演示人员、Docker Desktop、应用容器。

1. `demo.cmd start` 验证 Docker、Compose 和端口。
2. Compose 构建 `memory-palace-os:demo`，设置 `DEMO_MODE=true`，绑定本机端口。
3. 容器以非 root 用户启动单 worker 应用。
4. 脚本轮询 `/health`，只在状态为 `ok` 或 `healthy` 时返回成功。
5. 失败时脚本输出最近 80 行日志并返回非零退出码。

**状态变化：** 创建 Demo 网络、应用容器和独立数据卷。无真实外部通知。

## 场景运行

**前置：** 页面已连接，场景为 IDLE、PAUSED 或 FAILED。

1. 浏览器读取 `/demo/scenarios` 和 `/demo/environment`。
2. 浏览器为所选场景创建或恢复一个 active run。
3. Play/Step 请求携带 `expected_version`。
4. Controller 在 run lock 内验证版本和动作合法性。
5. Adapter 按 YAML 步骤生成证据；工具调用只记录为 Demo Adapter。
6. 页面轮询运行快照并按 `step_id` 选择最新 attempt。
7. 完成后页面允许下载包含完整 run 的 JSON 报告。

**拒绝路径：** 版本冲突返回 409 和最新快照；非法状态动作返回冲突，不覆盖已有证据。

## Pause、Stop 与 Reset

运行中动作只在原子步骤边界执行，优先级为 `reset > stop > pause`。

- Pause：保留已完成证据，状态变为 PAUSED，可继续。
- Stop：保留证据，状态变为 STOPPED，只能 Reset。
- Reset：清空当前 run 证据、耗时和错误，生成新 trace；不修改其他场景。
- `demo.cmd reset`：删除整个 Demo 数据卷并重建应用，四个场景回到 IDLE。

## 确定性失败恢复

任务拆解场景的 `recover-equipment-check` 固定在 attempt 1 产生 `TEMPORARY_TIMEOUT`，随后 attempt 2 成功。报告必须同时保留 FAILED 和 SUCCESS 两条证据，UI 默认显示最新成功 attempt，并把恢复次数计为 1。

## 断线与重连

页面连续三次获取运行快照失败后显示“连接中断”，不会推测或修改后台状态。恢复网络后点击“重新连接”读取服务端最新快照，再继续渲染。
