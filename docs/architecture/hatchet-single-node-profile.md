# Hatchet 单机自托管画像（票 02）

状态：已实测（2026-09-17）

## 版本边界

- Python SDK：`hatchet-sdk==1.40.1`，对应 Git tag `py/1.40.1`。
- 引擎/API/迁移/管理镜像：`v0.107.1`。两者版本号独立，不能把 SDK 的 `1.40.x` 当作 engine tag。
- CPU/单机验证镜像：
  - `ghcr.io/hatchet-dev/hatchet/hatchet-lite:v0.107.1`
  - `ghcr.io/hatchet-dev/hatchet/hatchet-engine:v0.107.1`
  - `ghcr.io/hatchet-dev/hatchet/hatchet-api:v0.107.1`
  - `ghcr.io/hatchet-dev/hatchet/hatchet-migrate:v0.107.1`
  - `ghcr.io/hatchet-dev/hatchet/hatchet-admin:v0.107.1`

`hatchet-lite` 把 API、engine、静态 UI 和一个自动 bootstrap entrypoint 放在同一进程；生产语义应优先使用 `hatchet-engine + hatchet-api + hatchet-migrate + hatchet-admin`，把迁移与管理初始化作为一次性 job。

## 资源画像

测试环境仍是 6GB WSL、Docker Desktop 4.88.1、Server 29.7.2；其他项目和景区 PostgreSQL/Redis/Nginx 容器未停止。Python worker 是单独的 Linux 测试容器，用于验证 SDK 行为。

### split profile（engine + API + PostgreSQL）

| 组件 | RSS |
| --- | ---: |
| `hatchet-engine:v0.107.1` | 64.69 MiB |
| `hatchet-api:v0.107.1` | 21.80 MiB |
| PostgreSQL 15.6 | 257.0 MiB |
| 测试 Python worker | 172.3 MiB |
| **合计** | **≈515.8 MiB** |

engine + API 从停止状态同时启动到 `/api/live` 返回 200：**0.539s**（本机缓存已热的模型/镜像）。

### lite profile（hatchet-lite + PostgreSQL）

| 组件 | RSS |
| --- | ---: |
| `hatchet-lite:v0.107.1` | 37.81 MiB |
| PostgreSQL 15.6 | 226.1 MiB |
| 测试 Python worker | 172.9 MiB |
| **合计** | **≈436.8 MiB** |

两者都很轻。`hatchet-lite` 省一个 API 进程，但会把 migrate/quickstart 自动放进 entrypoint；这适合本地演示，不应作为生产迁移策略。正式部署使用 split profile，workers 由业务 app 进程持有，不能再把这 172.3 MiB 当成额外常驻。

### 磁盘

`docker system df` 的镜像大小：

| 镜像 | 大小 |
| --- | ---: |
| `hatchet-lite` | 259 MiB |
| `hatchet-engine` | 102 MiB |
| `hatchet-api` | 104 MiB |
| `hatchet-migrate` | 51 MiB |
| `hatchet-admin` | 129 MiB |

镜像共享基础层；单机 Hatchet 栈的实际磁盘预算按 **0.3–0.4 GiB 镜像 + 约 70–100 MiB PostgreSQL 数据/WAL** 评估。测试独立 PostgreSQL 数据目录为 `73 MiB`，迁移完成后的逻辑数据库为 `18 MiB`。

### 与 6GB 的结论

Hatchet 自身很轻，但 TEI 两个模型同时常驻已经使用约 `4.57 GiB` RSS，并只剩约 `0.55 GiB` 可用。把 split Hatchet（engine/API/PG 约 `0.34 GiB`）、业务 app 和其他容器再算进去，6GB 很可能只能作为演示配置，且必须严格控制 app 内存；本票没有把 TEI、Hatchet、Jaeger 三者同时装入同一 VM，也没有测长期 retention/DB 增长，因此不能单独批准最终预算。ADR-0019 v4 要求 Jaeger 默认启用，若它也必须常驻，或 app 内存回升，票 07 应选择 8GB。

## 数据库隔离

### 同实例不同数据库

在景区 PostgreSQL 实例中创建独立 Hatchet 数据库和独立 role：

- database：`hatchet_research_shared`
- role：`hatchet_research_shared`
- migration：`hatchet-migrate:v0.107.1`
- 结果：migration 成功，`btree_gist` 扩展创建成功，public table 数 `164`，逻辑库大小 `16 MiB`，timezone `Etc/UTC`。

命令形态：

```powershell
docker run --rm `
  --network memory-palace-scenic_data-plane `
  -e DATABASE_URL='postgresql://<hatchet_role>:<password>@<business-pg-host>:5432/hatchet' `
  ghcr.io/hatchet-dev/hatchet/hatchet-migrate:v0.107.1 `
  /hatchet/hatchet-migrate
```

约束：

- 必须使用独立 database 和独立 role，不能把 Hatchet 表写进 `memory_palace` 的业务 schema。
- migration 会创建大量表并执行 `CREATE EXTENSION btree_gist`；实施时验证角色拥有该数据库及必要的扩展权限，或由 DBA 预创建 extension。
- PostgreSQL 必须是 `UTC`/`Etc/UTC`，否则 engine 会按 `DATABASE_ENFORCE_UTC_TIMEZONE` 规则拒绝启动。

### 独立 PostgreSQL 实例

官方 `docker-compose.yml` 的结构是同项目内单独 `postgres:15.6` 服务，`shm_size=4g`；本次该路径也完成 migration 和完整 durable workflow 运行。数据目录约 `73 MiB`，逻辑库约 `18 MiB`。

推荐：

- 本地演示：可以用业务 PostgreSQL 的同实例不同 database，减少一个常驻进程。
- 正式交付：优先独立 PostgreSQL 实例或至少独立 volume/备份策略，避免业务库和编排库共享故障域、升级窗口和恢复点。
- 无论哪种方案，Hatchet DB 只保存编排运行历史，不成为业务事实源。

## 迁移与管理命令

一次性 migration：

```powershell
docker run --rm --network <hatchet-network> `
  -e DATABASE_URL='postgresql://hatchet:********@postgres:5432/hatchet?sslmode=disable' `
  ghcr.io/hatchet-dev/hatchet/hatchet-migrate:v0.107.1 `
  /hatchet/hatchet-migrate
```

一次性配置和密钥初始化：

```powershell
docker run --rm --network <hatchet-network> `
  -e DATABASE_URL='postgresql://hatchet:********@postgres:5432/hatchet?sslmode=disable' `
  -v hatchet-config:/config `
  ghcr.io/hatchet-dev/hatchet/hatchet-admin:v0.107.1 `
  /hatchet/hatchet-admin quickstart `
  --skip certs --generated-config-dir /config --overwrite=false
```

生成 worker token：

```powershell
docker run --rm --network <hatchet-network> `
  -e DATABASE_URL='postgresql://hatchet:********@postgres:5432/hatchet?sslmode=disable' `
  -e SERVER_AUTH_COOKIE_DOMAIN=localhost `
  -e SERVER_GRPC_INSECURE=true `
  -v hatchet-config:/config `
  ghcr.io/hatchet-dev/hatchet/hatchet-admin:v0.107.1 `
  /hatchet/hatchet-admin token create `
  --config /config --name scenic-worker `
  --tenant-id 707d0855-80ab-4e1f-a156-f1c4546cbf52
```

迁移和执行顺序固定为：`postgres healthy → hatchet-migrate → hatchet-admin quickstart → hatchet-engine/hatchet-api → 业务 worker`。

发布责任：`hatchet-migrate` 由部署/CI 的 one-shot job 执行；engine/API 不应在应用启动时隐式迁移。升级门禁是 migrate 进程以 0 退出后才启动 engine/API，并在升级前备份 Hatchet DB。`hatchet-lite` 的 entrypoint 会自动执行 migrate/quickstart，仅适合本地演示。

## Python 人工中断

需要 Linux worker。`hatchet-sdk==1.40.1` 在 Windows 原生 Python 上初始化 worker 时实测失败：

```text
AttributeError: module 'signal' has no attribute 'SIGQUIT'
```

在 Docker/WSL Linux 中可运行。最小 durable event wait 形态：

```python
from datetime import timedelta
from pydantic import BaseModel
from hatchet_sdk import DurableContext, Hatchet

EVENT_KEY = "scenic:approval:decision"
hatchet = Hatchet()
workflow = hatchet.workflow(name="scenic-human-interrupt-research")

class IncidentInput(BaseModel):
    incident_id: str

class Decision(BaseModel):
    decision_id: str
    approved: bool

@workflow.durable_task(execution_timeout=timedelta(minutes=10))
async def await_decision(input: IncidentInput, ctx: DurableContext) -> dict:
    decision = await ctx.aio_wait_for_event(
        EVENT_KEY,
        payload_validator=Decision,
        scope=input.incident_id,
        lookback_window=timedelta(minutes=5),
    )
    return {"decision_id": decision.decision_id, "approved": decision.approved}
```

触发和恢复：

```python
run = workflow.run(IncidentInput(incident_id="incident-001"), wait_for_result=False)
hatchet.event.push(
    EVENT_KEY,
    {"decision_id": "decision-001", "approved": True},
    scope="incident-001",
)
result = run.result()
```

两个 SDK 1.40.1 注意点：

- `scope` 必须同时提供 `lookback_window`，否则抛 `Both lookback_window and scope must be provided together`。
- `aio_wait_for_event` 的第二个位置参数是 CEL `expression`；scope 必须写成 `scope=...`，不能把 `incident_id` 当第二个位置参数。

## profile 启停语义

实测流程：创建一个等待人工审批的 durable run → 停止 engine → 启动 engine → 推送审批事件 → 运行继续并完成。

已测范围是：lite 整进程 stop/start，以及 split profile 中只重启 engine；API、PostgreSQL 和 worker 在这些测试中保持运行。以下结论不外推到“同时重建 worker+DB 且停机超过 lookback”的场景。

观察结果：

- 等待中的 step 没有立即失败。
- engine 重启后 worker 的 action listener 自动重连；durable event listener 拉起之前排队的请求。
- `v1_runs_olap.readable_status` 在等待期间为 `RUNNING`，重启并收到事件后变为 `COMPLETED`。
- 因此 `docker compose stop` / `start` 对 durable run 的语义是**持久化暂停并恢复**，不是业务失败或重跑。若 worker 也停止，worker 重启后重新连接即可；事件侧应使用 `scope + lookback_window` 处理“事件先于重连”的竞态。

## 与“业务表是唯一事实源”的边界

- Hatchet 的运行、step、event wait、worker 记录只用于运行视图与恢复；不能用来决定事件是否关闭、是否审批、是否送达。
- 业务状态仍由 `scenic_incidents`、`scenic_commands`、`event_activities`、`llm_call_logs` 等 PostgreSQL 业务表承载。
- worker 恢复后应先按 `(incident_id, step, attempt)` 查询业务状态；若业务侧已经推进，Hatchet 运行应被标记或取消，而不是反过来覆盖业务表。
- compose profile 停止 Hatchet 时，业务 API 可以继续写业务表；恢复后由 reconciliation job/worker 重新拉起等待中的步骤。
- 正确的集成顺序是：业务事务先提交 `scenic_commands`/活动/卷宗意图，再发 Hatchet signal/event；发送失败由同一业务事实做可重试 outbox/reconcile。Hatchet 完成后再次以业务幂等键校验后才更新业务状态，不能用 Hatchet 状态覆盖业务状态。
- 不应把 Hatchet 内部 `WorkflowRun`/`v1_runs_olap` 状态直接暴露为关闭门禁或审批事实。

## 证据

- [evidence.json](/D:/Documents/memory-palace-os/artifacts/hatchet-research/evidence.json)
- 研究脚本：[worker.py](/D:/Documents/memory-palace-os/artifacts/hatchet-research/worker.py)、[trigger.py](/D:/Documents/memory-palace-os/artifacts/hatchet-research/trigger.py)
- Hatchet 版本来源：tag `py/1.40.1`，commit `4d9a0d4100397476132c51c96ba0dbb0c1cce5fa`；临时源码快照已清理。

## 未测限制

- 未把 TEI + Hatchet + Jaeger 同时启动做整机峰值测试。
- 未测试 worker 与 Hatchet 同时停机、PostgreSQL 故障、超过 5 分钟停机窗口或 retention 数据增长。
- 未做真实发布升级演练，只验证了当前版本的一次性迁移和初始化。
