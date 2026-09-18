# 景区 Agent 部署 profile、健康检查与预算（票 07）

状态：已定稿（2026-09-17）

## 1. 版本与边界

| 组件 | 固定版本 | 用途 |
| --- | --- | --- |
| `ghcr.io/huggingface/text-embeddings-inference` | `cpu-1.9.4` | bge-m3 嵌入、bge-reranker-base 重排 |
| `ghcr.io/hatchet-dev/hatchet/hatchet-engine` | `v0.107.1` | 持久化运行时引擎 |
| `ghcr.io/hatchet-dev/hatchet/hatchet-api` | `v0.107.1` | 运行视图/API |
| `ghcr.io/hatchet-dev/hatchet/hatchet-migrate` | `v0.107.1` | 一次性数据库迁移 |
| `ghcr.io/hatchet-dev/hatchet/hatchet-admin` | `v0.107.1` | 一次性配置初始化 |
| `jaegertracing/all-in-one` | `1.62.0` | OTLP 追踪查看 |
| `pgvector/pgvector` | `0.8.1-pg15-bookworm` | 业务唯一事实源与向量 |
| `postgres` | `15.6` | Hatchet 独立运行库 |

Hatchet 的 SDK 版本与 engine/API 版本独立。Python worker 使用 `hatchet-sdk==1.40.1`，票 08 已加入独立的 `scenic-agent-prototype` worker 验证真实四 agent 和 durable event wait；它使用单独的 prototype 镜像，不代表正式 worker 已完成业务接线。`HATCHET_POSTGRES_PASSWORD` 的本地默认值只用于本机演示，正式部署必须显式设置强密码。

## 2. compose profile 划分

所有服务的定义在 `deploy/docker-compose.yml`。未指定 profile 时只启动业务栈：`attachment-init`、`app`、`postgres`、`redis`、`nginx`。

| profile | 服务 | 用途 |
| --- | --- | --- |
| 默认 | `app`、`postgres`、`redis`、`nginx` | 当前业务与演示栈；不要求 TEI/Hatchet/Jaeger 常驻 |
| 默认 | `tei-embedding` | bge-m3 向量服务；与 app 同栈常驻（app 镜像已去 torch，ADR-0020） |
| `tei-reranker` | `tei-reranker` | bge-reranker-base 重排；`max-batch-tokens=1024` |
| `rerank-v2` | `tei-reranker-v2` | 可选更强 bge-reranker-v2-m3；与 base reranker 互斥，需 8GB 预算 |
| `agent-runtime` | `hatchet-postgres`、`hatchet-migrate`、`hatchet-admin`、`hatchet-token`、`hatchet-engine`、`hatchet-api`、`scenic-agent-prototype` | Hatchet split 运行栈 + 票 08 prototype worker；迁移和 quickstart 是一次性 job，正式 worker 仍由后续实现接入 |
| `tracing` | `jaeger` | OTLP 追踪；缺它不影响业务事实和关闭门禁 |

命令（使用与运行文档一致的 8090 业务端口，避让本机 8080）：

```powershell
# 默认业务栈
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml up -d

# TEI 基础模型（嵌入 + 重排）
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile tei-reranker up -d

# Hatchet 运行栈；migrate/admin 会按依赖顺序执行后退出
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile agent-runtime up -d

# Jaeger 按需
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile tracing up -d

# 可选更强重排；必须停掉 tei-reranker，避免两个服务抢 18001 端口
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml `
  --profile rerank-v2 up -d
```

停止可选平面而不动业务栈：

```powershell
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml --profile tei-reranker stop
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml --profile agent-runtime stop
docker compose -p memory-palace-scenic --env-file .env -f deploy/docker-compose.yml --profile tracing stop
```

Hatchet 升级顺序固定为：先备份独立 Hatchet DB，再执行 `hatchet-migrate`，其成功退出后才允许启动 `hatchet-engine`/`hatchet-api` 和 worker；不能通过业务启动隐式迁移。

## 3. 健康检查

`/health` 保持为存活探针，只判断进程和队列深度，Docker 的 app healthcheck 继续使用它。`/ready` 是就绪探针，调用统一 `HealthCheckerRegistry`，返回每个检查项和总体 `healthy/degraded/unhealthy`：

- `postgresql`、`redis` 为必需检查。
- 配置了 `SCENIC_TEI_EMBEDDING_HEALTH_URL` 时，TEI 嵌入不可用会让 `/ready` 返回 503；默认 profile 不设置该变量，因此不会误判。
- `SCENIC_TEI_RERANKER_HEALTH_URL`、`HATCHET_HEALTH_URL`、`JAEGER_HEALTH_URL` 为可选检查；不可用显示 `degraded`，仍返回 200。
- 未配置的检查项显示 `skip`，不伪造可用性。

启用 profile 时建议在 `.env` 设置：

```dotenv
SCENIC_TEI_EMBEDDING_HEALTH_URL=http://tei-embedding:80/health
SCENIC_TEI_RERANKER_HEALTH_URL=http://tei-reranker:80/health
HATCHET_HEALTH_URL=http://hatchet-engine:8733/ready
JAEGER_HEALTH_URL=http://jaeger:14269/
```

Hatchet engine 自身暴露 `http://hatchet-engine:8733/ready`，API 暴露 `http://localhost:8091/api/live`。Jaeger UI 默认 `http://localhost:16686`，OTLP HTTP 为 `4318`，gRPC 为 `4317`。

## 4. 离线准备

一次准备模型、固定镜像并可选择迁移 Hatchet：

```powershell
python scripts/prepare_scenic_agent_runtime.py `
  --model-cache-dir D:/memory-palace-models/huggingface `
  --reranker-dir D:/memory-palace-models/tei/bge-reranker-base-onnx `
  --migrate-hatchet
```

脚本行为：

1. `docker pull` 固定业务、TEI、Hatchet、Jaeger 镜像。
2. `snapshot_download` 固定 revision 下载 `BAAI/bge-m3`（HF cache）和 `BAAI/bge-reranker-base`（独立 ONNX 目录），不依赖损坏的 `.sync.part` 缓存。
3. `--migrate-hatchet` 时按 `postgres healthy → hatchet-migrate → hatchet-admin quickstart` 顺序执行，不启动假 worker。

只准备模型或只准备镜像时，使用 `--skip-images` 或 `--skip-models`；后者必须同时提供两个目录参数。该脚本不包含真实模型 Key，也不声称调用已发生。

## 5. 内存与 10GB 结论（2026-09-18 实测更新）

实测基线：TEI 双模型 RSS 约 4.57GiB；Hatchet split（engine+API+独立 PostgreSQL）本次冒烟约 0.27GiB，worker 另约 0.17GiB；Jaeger idle 约 0.01–0.2GiB。当前 app 仍内嵌 bge-m3，实测 idle 约 1.15GiB；票 03 的目标是迁移后降到约 0.3GiB。

因此：

- **本机现状（实测 2026-09-18）**：WSL 上限已调到 `memory=10GB`（实际 9.7GiB）。
- **TEI 常驻已实现**：`app` 约 0.3GiB + `tei-embedding` 约 2.7GiB（`--max-batch-tokens 2048`）+ PostgreSQL/Redis/Nginx/Jaeger 约 0.1GiB，实测峰值 ~3.0GiB / 9.7GiB；`/ready` 中 `tei_embedding` 为必需项且通过。
- **Hatchet 常驻预算**：TEI + Hatchet（engine/API/PG）+ Jaeger + 各可选 reranker 全部常驻，或使用 bge-reranker-v2-m3。TEI 同时常驻已不再是 8GB 的理由。
- **内存切换方式**：改 `%USERPROFILE%\.wslconfig` 的 `memory=`，执行 `wsl --shutdown`，重启 Docker Desktop；不通过修改 compose 默认值绕过内存事实。本次已备份原文件为 `.wslconfig.bak-*`。
- 6GB 下启动 TEI 时使用单进程 embedding + 单进程 reranker，不得把两个模型塞进同一 TEI 进程；reranker 失败按降级策略保留 vector order。

预算最终判定依据是容器 RSS/cgroup peak、`docker stats` 和 `/ready` 的实际状态；本机实测证据保存于 `artifacts/tei-profile/`、`artifacts/hatchet-research/` 与 `artifacts/scenic-agent-runtime-profile/`。本次 profile 冒烟实测：Hatchet migrate/admin 均以 0 退出，engine `/ready` 与 API `/api/live` 可达，Jaeger 健康且 UI 返回 200；冒烟后已停止可选 profile，保留数据卷。本票仍未把 TEI + Hatchet + Jaeger 同时启动做整机峰值测试，因此 8GB 是明确的安全边界，不是猜测。
## 6. 诊断与追踪下钻

`/admin/diagnostics` 是运维诊断页的数据源，展示模型运行时、最近真实调用、每日 token 配额、熔断状态和可选 Jaeger 链接。业务证据仍只来自 `llm_call_logs`；Jaeger 不可用不影响诊断、业务或关闭门禁。完整字段与配额语义见 `scenic-agent-diagnostics-observability.md`。
