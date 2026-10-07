# 景区全流程演示启动与操作手册

本文只描述演示环境的启动、打开和人工操作。业务事实仍以 PostgreSQL 为准，模拟控制只在受保护的 `/operations/scenic/` 入口。

## 一、需要启动什么

完整演示必须同时启动这些组件：

| 组件 | Compose 服务 | 作用 | 演示入口 |
| --- | --- | --- | --- |
| 应用 API | `app` | 鉴权、事件、任务、审批、Agent 命令 | 由 nginx 统一代理 |
| 异步 Agent worker | `scenic-agent-worker` | 执行 Hatchet 工作流和真实模型建议 | 无直接页面 |
| Hatchet | `hatchet-postgres`、`hatchet-migrate`、`hatchet-admin`、`hatchet-token`、`hatchet-engine`、`hatchet-api`、`hatchet-dashboard` | 持久化工作流、人工中断和历史 | http://127.0.0.1:8091/ |
| PostgreSQL + pgvector | `postgres` | SOP、事件、卷宗、任务、审批、调用记录的唯一事实源 | 无直接页面 |
| Redis | `redis` | 消息和运行队列 | 无直接页面 |
| TEI embedding | `tei-embedding` | `bge-m3` 1024 维向量检索 | 端口 `18000` |
| nginx | `nginx` | 统一 HTTP 入口 | `http://127.0.0.1:8090/` |
| Jaeger | `jaeger` | 可选链路追踪 UI | 端口 `16686` |

Hatchet Dashboard 使用独立登录，不走业务系统会话；本机 quickstart 的管理员账号见本地 `.env` 的 Hatchet 配置（凭据不入文档）。登录状态由 Hatchet Cookie 管理，演示时不要清除该站点的 Cookie。

### 本机演示账号与密码

> 以下凭据仅用于本机演示。源码正式打包、对外发布或截图外发前，必须删除本表并改由 secrets/环境变量注入。

| 角色 | 用户名 | 密码 | 入口 |
|---|---|---|---|
业务账号（`simulation-ops` / `wangfang` / `liming` / `chenyu`）的统一密码由 `SCENIC_ACCOUNT_PASSWORD`（容器内密钥卷）设置，Hatchet 管理员账号由 Hatchet quickstart 配置；凭据一律不入文档。

| 账号 | 入口 |
| --- | --- |
| 模拟运行准备员 `simulation-ops` | `/operations/scenic/`、`/operations/evaluation/` |
| 值班经理 `wangfang` | `/admin/`、`/simulator/wecom/` |
| 设备检修员 `chenyu` | `/assistant/` |
| 现场运营员 `liming` | `/assistant/` |
| Hatchet 管理员 | `http://127.0.0.1:8091/` |

启动脚本包含 Jaeger 时会设置 `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`。如果手工启动，需要同时设置该变量再重启 `app` 和 `scenic-agent-worker`；否则 Jaeger 页面会停留在无 trace 的空态。

不需要启动 `scenic-agent-prototype`；正式演示只使用 `scenic-agent-worker`。如果只需要看页面、不需要真实模型建议，可暂时不启动 worker，但“检索并核验 SOP”之后的异步建议将不可用。
启动脚本会将 App 的建议执行模式设为 `hatchet`，并使用共享 token 卷连接正式 worker。

## 二、脚本清单

| 脚本 | 用途 |
| --- | --- |
| `scripts\scenic-demo-start.ps1` | 检查 Docker、模型缓存、密钥卷，启动完整栈并等待健康 |
| `scripts\scenic-demo-status.ps1` | 查看容器、健康、密钥、入口 |
| `scripts\scenic-demo-open.ps1 -Mode Open` | 打开 5 个已按角色登录的演示窗口 |
| `scripts\scenic-demo-open.ps1 -Mode Verify` | 无窗口验证 5 个入口登录链路 |
| `scripts\scenic-demo-open.ps1 -Mode Auto` | 用可见浏览器自动跑完 15 步业务 UI，并在 Hatchet / Jaeger 做技术收口 |
| `scripts\scenic-demo-stop.ps1` | 停止容器，保留所有数据卷和密钥卷 |

## 三、启动

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-start.ps1
```

默认使用 `.env` 里的 `HTTP_PORT`（当前为 `8090`）和 `BGE_M3_CACHE_DIR`。如果模型缓存不在 `.env` 里：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-start.ps1 `
  -ModelCache 'D:\memory-palace-models\huggingface'
```

首次启动或代码/镜像更新后建议保留默认的 `--build`；只重启现有栈时可加 `-NoBuild`。

启动脚本会自动探测当前 Compose 的 egress 网关，并把它合并进 `SCENIC_PREP_ALLOWED_HOSTS`；Docker Desktop 重建网络后网关地址变化时，不需要手工改 `.env`。

启动完成后应先确认：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-status.ps1
```

预期：

```text
Health: ok
DeepSeek key: present
Demo password: present
```

## 四、打开演示窗口

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1
```

脚本会读取密钥卷里的统一密码，不在终端打印密码，并打开 5 个窗口：

1. `/operations/scenic/` —— `simulation-ops`，运行准备与时钟
2. `/admin/` —— `wangfang`，指挥中心
3. `/assistant/` —— `chenyu`，设备检修现场端
4. `/assistant/` —— `liming`，现场运营端
5. `/simulator/wecom/` —— `wangfang`，内部通知与回执联调（经理操作台）

窗口打开后，业务动作全部由人操作。脚本不会代替点击。

只验证登录链路：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1 -Mode Verify
```

自动跑完整链路并保存证据（默认可见浏览器）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1 -Mode Auto
```

CI 或不需要窗口时加 `-Headless`。

## 五、人工演示 17 步

### 第 1 步：准备运行

窗口：`/operations/scenic/`

操作：点击「准备新运行」。

预期：出现 `rain_vehicle_east_gate v1.0.0 · PAUSED` 和运行编号。

### 第 2 步：到设备异常

窗口：`/operations/scenic/`

操作：点击「到设备异常」（单步 2 秒）。

预期：出现 `VEHICLE_12_RIGHT_REAR_WHEEL` 告警；指挥中心自动出现下一步引导。

### 第 3 步：转为 P1 事件

窗口：`/admin/`

操作：点击「转为 P1 事件」。

预期：生成 `SJ-...` 运营事件；状态 `DETECTED`；优先级 P1。

### 第 4 步：提交现场证据

窗口：李明现场端 `/assistant/`

操作：填写现场说明，附上右后轮照片，点击「提交到正式事件卷宗」。

预期：卷宗出现文字和图片；事件继续推进到 `TRIAGED`（与下一步 SOP 命中共同构成前置条件）。

### 第 5 步：检索并核验 SOP

窗口：指挥中心 `/admin/`

操作：点击「检索并核验 SOP」。

预期：出现 `source_type=SOP` 的知识命中；后端为 `postgresql_pgvector`，维度 1024；事件保持 `TRIAGED`。

### 第 6 步：生成正式任务

窗口：指挥中心 `/admin/`

操作：点击「生成正式任务」。

预期：生成检修任务给陈雨；同时生成高风险审批（继续停运 + 启用备用车）；事件进入 `DISPATCHED`。

### 第 7 步：人工审批

窗口：指挥中心 `/admin/` → 审批中心

操作：批准审批，填写意见，例如「继续停运 12 号车，启用 7 号备用车」。

预期：审批 `APPROVED`，执行 `SUCCEEDED`。同一场地 60 秒内不能重复提交同一高风险决策，这是设计内冷却。

### 第 8 步：现场接单

窗口：陈雨现场端 `/assistant/`

操作：点击任务「开始」。

预期：事件进入 `ACKNOWLEDGED`；通知回执为已接单。

### 第 9 步：提交检修结果

窗口：陈雨现场端 `/assistant/`

操作：填写 `vehicle_12=ISOLATED`、`backup_vehicle_7=READY` 和检查项，提交。

预期：检修任务 `DONE`；事件进入 `MITIGATING`；回执为 `RECEIPT_RECORDED`。

### 第 10 步：到东门客流

窗口：`/operations/scenic/`

操作：点击「到东门客流」（单步 28 秒）。

预期：出现 `EAST_GATE_CAPACITY` 客流告警。

### 第 11 步：追加分流任务

窗口：指挥中心 `/admin/`

操作：点击「追加分流任务」。

预期：生成分流任务并派给李明。

### 第 12 步：提交分流回执

窗口：李明现场端 `/assistant/`

操作：开始分流任务并提交结果，例如单向分流、引导至镜湖。

预期：分流任务 `DONE`。

### 第 13 步：到风险恢复

窗口：`/operations/scenic/`

操作：点击「到风险恢复」（单步 60 秒）。

预期：设备告警和客流告警都恢复到阈值内。

### 第 14 步：解除风险并关闭事件

窗口：指挥中心 `/admin/`

操作：先点「核验并解除风险」，再点「关闭并形成审计卷宗」。

预期：`RESOLVED → CLOSED`；出现「事件已闭环」；可打开事件卷宗。

### 第 15 步：检查通知回执

窗口：内部通知接入环境 `/simulator/wecom/`

操作：查看通知投递和回执记录。

预期：每个任务都有 `RECEIPT_RECORDED`；短信和语音保持未配置，不产生假回执。

### 第 16 步：Hatchet 持久化运行历史

窗口：Hatchet `http://127.0.0.1:8091/`

操作：如出现登录页使用 Hatchet quickstart 管理员账号登录；进入 `Runs`，必要时点击 `Search past 7 days`。

预期：看到 `scenic-agent-advice`、暂停/恢复/重试/失败记录。讲解时强调 Hatchet 只保存运行历史，不替代 PostgreSQL 业务事实。

### 第 17 步：Jaeger Agent 技术调用链

窗口：Jaeger `http://127.0.0.1:16686/`

操作：在 `Search` 选择 `Service=scenic-agent-trunk`，点击 `Find Traces`，打开 `scenic.incident_command` trace。

预期：看到 `context_trigger`、`router`、`memory_ops` span、耗时和重试；Jaeger 不参与关闭门禁。

## 六、成功判据

| 对象 | 期望 |
| --- | --- |
| 事件 | `CLOSED` |
| 卷宗 | 现场文字、图片、SOP 命中、审批结果、两条任务回执 |
| 检修任务 | `DONE` |
| 分流任务 | `DONE` |
| 设备告警 | `RECOVERED` |
| 客流告警 | `RECOVERED` |
| 高风险审批 | `APPROVED` + `SUCCEEDED` |
| 通知回执 | 每个任务各一条 `RECEIPT_RECORDED` |
| SOP 命中 | `source_type=SOP`、`postgresql_pgvector`、1024 维 |
| 案例沉淀 | 关闭时写入一条 `CASE` 向量 |
| Hatchet | 最近运行、pause/resume/retry 历史可见 |
| Jaeger | `scenic.incident_command` 根 span 与 Agent span 可见 |

## 七、自动验证与证据

```powershell
# 5 个入口登录链路
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1 -Mode Verify

# 15 步业务 UI 流程 + Hatchet/Jaeger 技术收口，证据写入 artifacts\scenic-e2e\auto-demo
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1 -Mode Auto

# Hatchet + PostgreSQL 建议路径
uv run --no-project --with-requirements requirements.txt python scripts\verify_hatchet_advice_path.py

# 人工中断
uv run --no-project --with-requirements requirements.txt python scripts\verify_hatchet_human_interrupt.py
```

## 八、停止

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-stop.ps1
```

该脚本只执行 `docker compose down`，不删除 `pg-data`、`redis-data`、`hatchet-pg-data`、附件卷或密钥卷。

## 九、常见问题

- `502 Bad Gateway`：应用或 nginx 上游刚重建。重新执行 `scenic-demo-start.ps1` 或 `docker restart memory-palace-scenic-nginx-1`。
- `DeepSeek key: missing`：执行 `scripts\set_deepseek_secret.ps1 -VolumeName memory-palace-secrets`。
- `Demo password: missing`：执行 `scripts\set_scenic_account_secret.ps1 -VolumeName memory-palace-secrets`。
- 模型缓存缺失：先执行 `scripts\scenic.ps1 prepare-model -ModelCache <绝对路径>`。
- Hatchet 工作流不推进：确认 `scenic-agent-worker` 正在运行；它不在 nginx 里，没有页面。
- 端口冲突：修改 `.env` 的 `HTTP_PORT`，重新启动；演示默认使用 `8090`，不要使用 `8080`。
