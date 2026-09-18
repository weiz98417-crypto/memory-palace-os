# Enterprise Demo V1 测试结果

> **Status: superseded (历史快照)** — 本文件记录的 ChromaDB / 1536 维 embedding 与旧四层架构描述，已被 ADR-0007（PostgreSQL pgvector 为唯一向量后端）、ADR-0018（Agent 链为景区事件主干）与 ADR-0019（Agent 运行时技术栈）取代。内容仅作历史证据保留，不是当前实现或实施依据。


## 结论

企业演示版在 Windows + Docker Desktop 环境通过后端全量测试、聚焦回归、真实浏览器工作流和 Docker 运维命令验收。

## 自动化测试

```powershell
scripts\demo.cmd verify
```

- 结果：176 passed
- Python：3.11.15（Docker runtime）
- 总覆盖率：36%
- `src/memory_palace/demo/scenario_controller.py`：88%
- `src/memory_palace/demo/models.py`：100%
- `src/memory_palace/demo/adapters.py`：100%
- 测试容器：完成后由 `--rm` 自动删除

聚焦 Demo 回归：

```powershell
docker compose -f deploy/docker-compose.demo.yml run --rm --no-deps app pytest -q -p no:cacheprovider --no-cov tests/unit/test_scenario_controller.py tests/integration/test_demo_scenarios.py tests/integration/test_demo_reset.py
```

- 结果：22 passed
- 覆盖：展示延迟与业务耗时隔离、步骤超时、失败边界 Stop/Reset、非法状态转换、失败证据与重试恢复、并发 Play、四场景契约、报告契约、跨场景隔离、Demo 路由安全隔离

## 浏览器 QA

运行环境：Playwright 1.62.0 + 本机 Microsoft Edge，无模拟 DOM。

通过工作流：

1. 首屏、四场景和环境能力载入
2. 单步执行和 attempt 证据
3. Play/Pause 步骤边界
4. 完成和 JSON 报告下载
5. 运行中 Reset 和 Stop
6. 跨场景状态与证据保留
7. 固定失败 attempt 1 与恢复 attempt 2
8. 三次轮询失败后的断线状态和重连
9. 全屏进入与退出
10. 1366/1440/1920/1179/899 视口和抽屉断点
11. 后端重启后显示“运行已中断”，禁用 Play/Step，Reset 后恢复 IDLE
12. 旧版本轮询快照被拒绝，不能覆盖较新的运行版本
13. Demo 模式下旧 Admin、Webhook、旧 Demo、静态管理页和 OpenAPI 均返回 404
14. 展示等待不计入业务耗时，浏览器实测单步证据为 1 ms

浏览器结果：console errors 0，unexpected request failures 0，HTTP 4xx/5xx 0。故意断线产生的 `ERR_INTERNET_DISCONNECTED` 只在故障注入窗口内视为预期。

## Graphify 架构校验

```powershell
graphify update .
```

- 生成日期：2026-07-27
- 提交基线：`a67de969`，提取范围包含完整候选工作区
- 源文件：242 个
- 图谱规模：2404 个节点、3985 条边、200 个社区
- 导入环：未发现
- 核心枢纽：`ScenarioController` 为当前连接度最高节点，共 77 条边
- 报告：`graphify-out/GRAPH_REPORT.md`

Graphify 对 8 个生成型 JSON 文件报告零节点；这些文件是仪表盘、场景运行结果或报告样本，不是代码依赖源，不影响架构校验结论。

## 已知非阻断警告

- Starlette TestClient 的 httpx 弃用提示
- ChromaDB mock embedding 新接口提示
- `test_file_ops.py` 文档字符串 escape sequence 提示

这些警告不影响 V1 演示，但依赖升级前应纳入清理计划。
