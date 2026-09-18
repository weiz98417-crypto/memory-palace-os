# ADR-0020: 景区 Agent 主干依赖锁定与 1024 维一致性契约

## 状态

已接受（2026-09-17）。补充 ADR-0019（Agent 运行时技术栈选型）与 ADR-0009（本地 bge-m3）。

## 背景

ADR-0019 定了技术栈，但没定"具体安装为哪个包、哪个版本能同时安装"。
票 08 的真实 prototype 已跑通四 agent + Hatchet + LiteLLM + TEI，但当时的依赖是单独的
`requirements-scenic-agent-prototype.txt`，与正式 `requirements.txt` 分开；避免把未确认可共存的依赖
合并进生产镜像。

同时，向量层有两个独立的 bge-m3 运行时：本地 sentence-transformers 路径和 TEI HTTP
路径。两者必须可以共用同一个 1024 维 cosine 空间，否则已有向量会静默失真。

## 决策

### 1. 依赖组合

采用 `pydantic-ai-slim` 而不是 `pydantic-ai` 全量包，并以下列版本作为生产锁定：

| 包 | 锁定版本 | 原因 |
| --- | --- | --- |
| `pydantic-ai-slim` | `2.43.0` | 四 agent 契约层；不带 openai extra |
| `pydantic-graph` | `2.43.0` | 由 slim 作为逆向依赖引入，举止比特同 |
| `litellm` | `1.101.0` | 进程内模型网关；只走 api.deepseek.com |
| `hatchet-sdk` | `1.40.1` | 编排与人工中断；engine 镜像 `v0.107.1` |
| `opentelemetry-sdk` | `1.44.0` | 跟踪；与 OTLP gRPC exporter 同版本 |
| `opentelemetry-exporter-otlp-proto-grpc` | `1.44.0` | OTLP 导出 |
| `pydantic` | `>=2.12,<3` | slim 2.43.0 要求 `pydantic>=2.12` |
| `pydantic-settings` | `>=2.14.1,<3` | litellm 1.101.0 与 hatchet-sdk 的交集 |

实测可共存的实际解（来自已验证的 prototype 镜像）：
`pydantic==2.13.5`、`pydantic_core==2.46.5`、`openai==2.54.0`、`httpx==0.28.1`、
`httpx2==2.13.0`、`grpcio==1.84.0`、`pydantic-settings==2.15.0`、`fastapi==0.141.1`。

**不允许：**

- 安装 `pydantic-ai` 全量包；它的 `openai` / `openai-realtime` / `openrouter` 等 extra
  会引入 `openai>=3.8.0`，与 litellm 的 `openai>=2.20.0,<3.0.0` 直接冲突。
- 为 `pydantic-ai-slim` 开启任何携带 `openai>=3.8.0` 的 extra。
- 把 prototype 和生产依赖混在同一个镜像里靠运气解决。

**隔离方案（仍然保留）：** prototype worker 继续使用独立镜像
`memory-palace-scenic-agent-prototype:local`，不把 prototype 依赖混入正式 app 镜像。
合并前提是上表锁定已经在正式 `requirements.txt` 里生效并通过全量测试。

### 2. 模型修订必须钉住

`BAAI/bge-m3` 在本地 sentence-transformers 路径与 TEI 容器路径都必须钉到同一个 Hugging Face revision：

```
BAAI/bge-m3 @ 5617a9f61b028005a4858fdac845db406aefb181
```

两处都不得使用漂移的 `BAAI/bge-m3` 标签：TEI 从本地缓存目录读取，
本地路径从 `local_files_only=True` 缓存读取，两者都不会自己告诉你它实际加载了哪个 revision。
虚数据库侧的 `vector_index_versions.model_version` 也必须记录同一 revision，
供诊断和审计比对。

## 1024 维一致性验证方法

### 取样

| 层 | 规模 | 说明 |
| --- | --- | --- |
| 固定契约样本 | 20 documents + 5 queries = 25 向量 | 与票 03 产物一致；可离线、可重复 |
| 真实库回归 | 全部已发布 SOP/经验索引 | 切换前在 staging 用 TEI 重新编码并比对 top-k |

固定样本的向量与评分已保存在 `artifacts/tei-migration/`（`local_vectors.json`、
`tei_vectors.json`、`score_distribution.json`、`db_retrieval_distribution.json`），
配套脚本 `compare_distribution.py` / `compare_db_retrieval.py` 可重复执行。

### 容差（必须全部满足）

| 指标 | 阈值 | 本次实测 |
| --- | --- | --- |
| 向量维度 | 恰好 1024 | 25/25 |
| `max_abs_diff`（逐元素） | 参考包络，不作否决（见下方实测） | 全量 143 向量：p50 `3.10e-07` / p95 `8.00e-07` / p99 `2.13e-06` / max `2.69e-06` |
| `min_cosine`（同一输入两个运行时） | `>= 0.99999999` | `0.999999999996` |
| 归一化残差 `abs(norm-1)` | `<= 1e-5` | 最大 `1.123e-07` |
| `all_top1_same` | `true` | `true` |
| `all_top3_overlap` | `true` | `true` |
| `all_top5_ids_same` | `true` | 真实 PostgreSQL SOP Top-5，5/5 query 完全相同 |
| `threshold_hit_count_match` | `true` | `true` |
| `max_abs_score_delta`（检索评分，100 对） | `<= 1e-6` | `6.307e-07`（p95 `4.365e-07`） |

不得做 bitwise equality 断言；不同运行时的 BLAS kernel、批大小与量化路径不同，逐位相等不是可靠契约。

**2026-09-18 全量重算后修正**：票 03 的 25 样本给出的 `max_abs_diff <= 5e-7` 在真实全量上不成立。143 条已发布向量逐行重算后实测如上，尾部达 `2.69e-06`。因此**逐元素差异改为参考包络，不再作为否决条件**；否决依据收紧为检索行为：`min_cosine`、`min_top1_same`、`all_top5_ids_same`、`threshold_hit_count_match`。全量 10 条业务查询实测 Top-5 ID **10/10 完全一致**、最大评分漂移 `1.0e-06`；证据：`artifacts/tei-reembed/parity.json`、`retrieval-before.json`、`retrieval-after.json`。

### 回滚判据（任一条成立即回滚）

1. 任一固定样本维度 ≠ 1024，或向量包含 `NaN`/`Inf`。
2. `min_cosine < 0.99999999`、`max_abs_score_delta > 1e-5`，或逐元素差异超出上方实测包络的 4 倍。
3. 任一 query 的 Top-1 命中变化，或 Top-5 集合不再完全相同。
4. `threshold_hit_count` 在任一查询上发生变化。
5. TEI 模型 revision 与 `vector_index_versions.model_version` 不一致，或 `/info` 返回的模型名不是
   钉住的 `BAAI/bge-m3`。
6. 真实库回归中出现客户可见的依据退化（旧命中变未命中）。

回滚动作：把 `vector_index_versions.provider/model_version` 改回 `LOCAL` 并重新指向本地 runtime；
不删除已有 `knowledge_vectors` 行，不伪造新的命中。审计事实仍以 `knowledge_retrieval_snapshots`
与 `llm_call_logs` 为准。

## 后果

- 正式 `requirements.txt` 可以合并 prototype 依赖，但必须以本 ADR 的锁定与
  `tests/unit/test_agent_runtime_dependency_lock.py` 为门禁；prototype 镜像隔离仍然保留。
- 向量切换不再依赖"看起来能检索"，而是以可复现的容差与 top-k 回归作为硬门禁。
