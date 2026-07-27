# 企业演示版故障处理手册

## 页面打不开

```powershell
scripts\demo.cmd status
curl.exe http://localhost:8000/health
scripts\demo.cmd logs
```

若端口被占用，设置新的本机端口后启动：

```powershell
$env:DEMO_PORT = "8010"
scripts\demo.cmd start
```

## 页面显示连接中断

1. 不要反复点击 Play 或 Reset。
2. 确认 `/health` 可用。
3. 点击页面“重新连接”，页面会读取服务端最新 run。
4. 若服务已重启，页面会将原 run 标记为“运行已中断”；点击 Reset 创建干净运行后重新开始。

## 场景卡在 RUNNING

1. 等待当前原子步骤结束。
2. 点击 Stop；若需要清空证据，点击 Reset。
3. 查看日志中的 action 请求和异常。
4. 仍无法恢复时执行 `scripts\demo.cmd reset`。

## Verify 测试容器不退出

当前实现会在 pytest 会话结束时关闭 SQLite、Chroma 和通知线程池。若再次发生：

1. 用 `docker ps -a --filter name=memory-palace-demo-app-run` 确认一次性容器。
2. 保存测试输出和 `docker top` 结果。
3. 只终止对应 `memory-palace-demo-app-run-*`，不要操作其他项目容器。
4. 检查新增全局客户端、线程池或后台 task 是否缺少 teardown。

## 演示前恢复基线

```powershell
scripts\demo.cmd reset
scripts\demo.cmd verify
scripts\demo.cmd status
```

Reset 只允许作用于 `memory-palace-demo-data`。不要复用或删除其他 Compose 项目的卷和容器。
