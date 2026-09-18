# pgvector 数据契约

本文件说明正式链路里 pgvector 必须承载哪些数据、这些数据从哪里产生、如何校验。它不是“先灌一批向量让检索看起来能用”，而是业务事实表的派生索引。

## 唯一后端

- 存储：PostgreSQL `knowledge_vectors` 表，HNSW 余弦索引。
- 索引版本：`index_name = knowledge_vectors_bge_m3_v1`，`dimension = 1024`，`index_status = READY`。
- 模型：`BAAI/bge-m3` @ `5617a9f61b028005a4858fdac845db406aefb181`，生产 runtime 为 TEI（`model_version = tei-bge-m3-1.9.4-1024-v1`），回滚 runtime 为本地 sentence-transformers（`model_version = local-bge-m3-1024-v1`）；CPU 可运行（`EMBEDDING_CPU_THREADS`，默认 4）。容差与回滚判据见 ADR-0020。
- 租户：每条向量必须有 `venue_id`；所有读写都按 `venue_id` 过滤。
- 版本行：`vector_index_versions` 必须存在对应 `READY / 1024` 记录，`provider` 与 `model_version` 必须反映实际生成向量的 runtime（TEI 或 LOCAL），否则启动检查与迁移校验都会失败。

PostgreSQL pgvector 是本产品的唯一向量后端，不存在第二套向量后端或影子后端；产品不提供其他向量库的迁移工具（见 ADR-0007）。

## 必须存在的三类数据

| 类别 | 事实来源 | `source_type` | `doc_id` 约定 | 写入路径 |
| --- | --- | --- | --- | --- |
| SOP | `sop_documents`（`status = PUBLISHED`） | `SOP` | `sop:{venue_id}:{sop_id}` | 景区切片 `_ensure_story_sop`；SOP 发布流程 |
| 经验/知识卡 | `experience_cards`（已发布版本） | `KNOWLEDGE` / `EXPERIENCE` | 由发布流程给定 | 经验发布流程 |
| 处置案例 | `scenic_incidents` + 任务回执 + 审批（关闭事件时聚合） | `CASE` | `evt_{event_id}` | `_write_case_memory`，随事件关闭产生 |

### 关于 SOP 预置文本

景区切片启动时会按场地位写入 1 条《雨后观光车复运与分流 SOP》：文本来自产品内置处置标准，先落 `sop_documents`（含版本、审核人、发布时间），再索引进 pgvector。这是**产品预置标准**，不是伪造的检索结果；替换为客户真实 SOP 时走同一张表与同一条索引路径。

## 检索契约

- 任何查询必须携带 `venue_id`，跨场地检索不存在。
- SOP 检索必须显式过滤 `source_types=["SOP"]`。历史 CASE 会持续累积，若只按相似度取前 N 条，SOP 会被案例挤出，导致处置环节拿不到标准依据。
- 景区 SOP 检索阈值 0.55；低于阈值视为“没有可用依据”，不得伪造命中。
- embedding 不可用时返回“向量检索不可用”，不写零向量、不返回假命中。

## 校验方式

```powershell
$env:DATABASE_URL = "postgresql://<user>@127.0.0.1:5432/memory_palace"
uv run --no-project --with "psycopg[binary]" python scripts/verify_vector_data.py
```

脚本会检查：索引版本与维度、每个场地三类向量的数量、以及**每条已发布 SOP 是否都有对应向量**。缺少必需数据时以非零退出码结束，并列出缺口。

## 明确禁止

- 用合成语料、零向量或占位向量充当业务数据。
- 让检索“看起来命中”而实际没有对应事实行。
- 在正式链路里保留第二套向量后端或影子索引。
