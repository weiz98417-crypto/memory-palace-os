# 景区应急管理与实时监控 · 现场演示流程

本文档用于人工演示“雨后观光车异常 → 东门客流上升”这条垂直故事。**全程由人操作真实界面**：脚本只负责打开并按角色登录好窗口，不代替任何业务动作，也不是播放/录像。

## 一、演示前准备

| 项目 | 值 |
| --- | --- |
| 演示入口 | `http://127.0.0.1:8090/`（Docker 栈）或本机栈同端口 |
| 指挥中心 | `/admin/` —— 值班经理 |
| 员工现场端 | `/assistant/` —— 现场运营 / 设备检修 |
| 内部系统接入环境 | `/simulator/wecom/` —— 内部通知与回执 |
| 受保护运行准备 | `/operations/scenic/` —— 仅 `simulation-ops`，仅本机/受信入口 |
| 账号 | `simulation-ops`、`wangfang`、`liming`、`chenyu` |
| 密码 | 由 `SCENIC_ACCOUNT_PASSWORD`（容器为 secret 卷）统一设置，不写入文档与截图 |

启动演示环境（Docker 栈）：

```powershell
$env:BGE_M3_CACHE_DIR = 'D:\memory-palace-models\huggingface'
powershell -ExecutionPolicy Bypass -File scripts/scenic.ps1 start -ModelCache $env:BGE_M3_CACHE_DIR
```

或用本机原生栈（PostgreSQL 15432 + Redis 16379 + 应用 8090）：`artifacts/scenic-e2e/local-runtime.ps1 -Command run`。

## 二、打开演示窗口

```powershell
$env:SCENIC_DEMO_PASSWORD = '<统一演示密码>'
uv run --with playwright python scripts/scenic_demo_launcher.py
```

脚本会开 5 个互相独立的浏览器窗口并各自登录好，按 2 列平铺：

1. 运行准备 —— `simulation-ops`
2. 指挥中心 —— `wangfang`
3. 现场端 —— `chenyu`
4. 现场端 —— `liming`
5. 内部通知接入环境 —— `liming`

窗口开好后**由你手动操作**，脚本不会点击任何业务按钮。想先验证登录链路而不开窗口，加 `--headless --verify-only`。

## 三、演示流程（15 步）

> 每步都写清“在哪个窗口、点什么、应该看到什么”。带 ⏱ 的步骤受 60 秒高风险决策冷却限制。

1. **运行准备 → 准备新运行**：点击「准备新运行」。预期：出现 `rain_vehicle_east_gate v1.0.0 · PAUSED` 与运行编号。
2. **运行准备 → 到设备异常**：点击「到设备异常」（单步 2 秒）。预期：监测信号与 `VEHICLE_12_RIGHT_REAR_WHEEL` 告警出现（指挥中心会自动弹出下一步引导）。
3. **指挥中心 → 转为 P1 事件**：点击「转为 P1 事件」。预期：生成运营事件（业务编号 `SJ-...`），状态 `DETECTED`，P1。
4. **现场端（李明）→ 提交现场证据**：在事件卡片里填写现场说明，附上一张右后轮照片，点「提交到正式事件卷宗」。预期：卷宗出现文字与图片附件；状态推进到 `TRIAGED`（需同时有 SOP 命中，见下一步）。
5. **指挥中心 → 检索并核验 SOP**：点击「检索并核验 SOP」。预期：命中 `source_type=SOP` 的知识条目，后端显示 `postgresql_pgvector`、1024 维；事件状态 `TRIAGED`。
6. **指挥中心 → 生成正式任务**：点击「生成正式任务」。预期：生成检修任务（派给陈雨）与一条高风险审批（继续停运 + 启用备用车），事件状态 `DISPATCHED`。
7. **指挥中心 → 审批中心 → 批准** ⏱：打开审批中心，批准该审批并填写意见（如“继续停运 12 号车，启用 7 号备用车”）。预期：审批状态 `APPROVED`、执行 `SUCCEEDED`。*同一场地 60 秒内不能重复提交同一高风险决策，这是设计内的限流。*
8. **现场端（陈雨）→ 接单**：在任务里点开始。预期：事件状态推进到 `ACKNOWLEDGED`，通知回执变为已接单。
9. **现场端（陈雨）→ 提交检修结果**：填写结构化结果（`vehicle_12=ISOLATED`、`backup_vehicle_7=READY`、检查项），提交。预期：任务 `DONE`，事件 `MITIGATING`，回执变为 `RECEIPT_RECORDED`。
10. **运行准备 → 到东门客流**：点击「到东门客流」（单步 28 秒）。预期：出现 `EAST_GATE_CAPACITY` 客流告警。
11. **指挥中心 → 追加分流任务**：点击「追加分流任务」。预期：生成分流任务并派给李明。
12. **现场端（李明）→ 提交分流回执**：开始任务并提交结果（单向分流、客流引导至镜湖）。预期：任务 `DONE`。
13. **运行准备 → 到风险恢复**：点击「到风险恢复」（单步 60 秒）。预期：设备与客流信号恢复到阈值内。
14. **指挥中心 → 核验并解除风险 → 关闭并形成审计卷宗**：先点「核验并解除风险」，再点「关闭并形成审计卷宗」。预期：状态 `RESOLVED → CLOSED`，出现「事件已闭环」，可点「查看事件卷宗」。
15. **内部通知接入环境 → 查看通知**：切到第 5 个窗口，检查通知投递与回执记录。预期：能看到本场地内部通知的送达/接单/回执，短信与语音显示未配置（不产生假回执）。

## 四、成功判据

演示结束时，指挥中心与现场端应同时满足：

| 对象 | 期望 |
| --- | --- |
| 运营事件 | `CLOSED`，卷宗含现场文字、图片附件、SOP 命中、审批结果、两条任务回执 |
| 检修任务 / 分流任务 | 均 `DONE` |
| 设备告警 / 客流告警 | 均 `RECOVERED` |
| 高风险审批 | `APPROVED` + `SUCCEEDED` |
| 内部通知回执 | 每个任务各一条 `RECEIPT_RECORDED` |
| SOP 命中 | `source_type=SOP`，`backend=postgresql_pgvector`，1024 维 |
| 案例沉淀 | 关闭时写入一条 `CASE` 向量（可在 SOP/知识中心或 `knowledge_vectors` 中核验） |

## 五、注意事项

- **模拟控制只在受保护入口**：业务界面（指挥中心/现场端/接入环境）不出现播放、暂停、倍速、单步等演示控件；准备与时钟只存在 `/operations/scenic/`，且要求 `simulation-ops` 身份 + 本机/受信入口。
- **冷却是真实规则**：同一场地 60 秒内重复提交同一高风险决策会被拒绝，等待后重试即可。
- **端口**：演示统一使用 `8090`（8080 常被其他本地项目占用）。如需更换，改 `.env` 的 `HTTP_PORT` 并重启 nginx。
- **不要伪造**：外部短信/语音渠道保持未配置；未配置模型或知识时系统应报“不可用”，不会返回假命中。
- **Docker 启动失败时**：若报 `sailor-ingest.sock` / `docker-secrets-engine` 无法删除，把这两个目录改名备份后重启 Docker Desktop（见 tasks.md 记录）。

## 六、证据与自动验证

- 界面证据：`uv run --with playwright python scripts/scenic_demo_launcher.py --headless --verify-only` 会为每个角色截图到 `artifacts/scenic-e2e/ui-demo/`。
- 业务链路验证（不经过界面）：`scripts/scenic_e2e_journey.py`，产出 `journey-evidence.json` 与 `journey-database-evidence.json`。
- 向量数据核验：`uv run --no-project --with "psycopg[binary]" python scripts/verify_vector_data.py`。
- 演示现场的截图建议覆盖：指挥中心闭环态、事件卷宗、接入环境回执、运行准备入口（这四张足以证明全链路）。
