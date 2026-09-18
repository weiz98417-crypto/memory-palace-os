# 嵌入与重排迁移到 TEI 的设计（票 03）

状态：已实现（2026-09-17，票 m4-01）。

状态：迁移设计完成，待实现（2026-09-17）

## 1. 决策摘要

- `LocalEmbeddingBackend` 保留原接口和类名；新增 `TEIEmbeddingBackend` 作为同接口的 HTTP adapter，公共调用点只换 backend factory。
- 不把 rerank 放进 embedding adapter。新增独立的 `RerankerBackend`，由 `EvidenceBackedKnowledgeRetriever` 在 pgvector 召回和关系校验之后、最终 top-k 选择之前调用。
- 现有 `knowledge_vectors` 继续使用同一 PostgreSQL 表和 `knowledge_vectors_bge_m3_v1` 索引名，不建影子后端；模型 revision 和 1024 维 cosine 契约不变，因此不需要新索引名。
- 现有本地 bge-m3 向量可以直接与 TEI 查询向量共用；实测 Top-5 SOP 检索 ID 完全一致。正式切换前仍应做一次受控 re-embed，并把 `vector_index_versions.provider/model_version` 更新为 TEI 来源，避免把 TEI 生成的向量误标为 LOCAL。
- 空输入、截断、超时和异常都不允许伪造向量或引用；embedding 不可用时向量检索失败，rerank 不可用时退回 pgvector 原始排序并明确记录降级。
- 远程生成的 embedding 向量仍需在 adapter 内校验 1024 维、数量、有限数值和归一化误差；不直接信任 HTTP 响应。
- 与 ADR-0009 的独立索引约束对齐：该约束针对引入不同远程 embedding 服务或模型升级。本方案仍使用同一 `BAAI/bge-m3` revision、同一 1024 维 cosine 空间和本地 TEI 运行，故不新建第二个索引；但 provider/model_version 必须在全量 re-embed 后如实更新。若更换模型 revision 或换用不同 embedding 服务，必须新建索引版本并重新生成向量。

## 2. Embedding seam

现有 seam 是：

```python
class LocalEmbeddingBackend:
    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]: ...
    def probe(self) -> dict[str, object]: ...
```

保持不变，并抽出协议：

```python
class EmbeddingBackend(Protocol):
    model_name: str
    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]: ...
    def probe(self) -> dict[str, object]: ...
```

- `EmbeddingClient` 的构造类型从具体 `LocalEmbeddingBackend` 改为 `EmbeddingBackend`，异步入口 `embed_text/embed_batch` 不变。
- `PalaceVectorStore` 只依赖 `embed_batch_sync` 和 `probe`，`query_experience/upsert_experience/health/verify_documents` 的对外签名不变。
- `TEIEmbeddingBackend` 使用同步 `httpx.Client` 和 `/embed`，因为当前 `PalaceVectorStore` 是同步 seam；`EmbeddingClient` 仍通过 `asyncio.to_thread` 调它，不阻塞 FastAPI 事件循环。
- 为保持现有本地语义，adapter 在发 HTTP 前仍应用 `MAX_TEXT_LENGTH=8192` 字符上限；TEI 当前 `max-batch-tokens=2048` 会再按 token 截断。若需要完整 8192-token 上下文，必须按票 01/07 重新分配 8GB，不得静默改变语义。
- `TEIEmbeddingBackend` 按 `TEI_MAX_CLIENT_BATCH_SIZE=16` 分片；空列表直接返回 `[]`，不发 HTTP。
- 每个响应必须满足：数量等于输入数量、每向量 1024 维、数值有限、norm `abs(norm-1) <= 1e-5`。违反时抛错，不自动补零、不截断维度、不改成另一个模型。
- `probe()` 调 `/info` 或 `/health`，返回 `status/model/dimension/pooling/max_input_length`；健康检查不进行生成式调用。

## 3. Reranker seam

重排放在检索模块内。调用方不应知道 TEI URL、rerank 分数或失败策略。

```python
class RerankerBackend(Protocol):
    model_name: str
    def rerank_sync(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int,
    ) -> list[dict[str, Any]]: ...
```

- `TEIRerankerBackend` POST `/rerank`，请求 `{"query": ..., "texts": [...]}`；候选列表为空时直接返回 `[]`，因为 TEI 对空 `texts` 返回 HTTP 400。
- 单个 rerank 文本按 TEI 的 512-token 上限自动截断；adapter 不自行改变文本正文或引用元数据。
- TEI 返回 `[{index, score}]`，adapter 必须校验 index、去重、按 score 降序映射回原候选；不得改变租户或来源元数据。
- `EvidenceBackedKnowledgeRetriever.__init__(database, vector_store, reranker=None)` 增加可选注入。
- 执行顺序固定为：pgvector 多策略召回 → 关系真值/租户/授权校验 → `reranker.rerank_sync` → source priority + final score 排序 → `top_k`。`ScenicAreaOperations._command_retrieve_sop` 也必须复用同一个 helper，不能绕过 rerank 写入另一套 SOP 证据。
- `semantic` 与 `broad` 两次召回分别保留原始 vector score；重排只作用于已经通过 `_verify_candidate` 的候选。
- 无 reranker：`rerank_status=DISABLED`，排序退回 vector score。
- reranker 超时/失败/响应非法：`rerank_status=FAILED`，保留 pgvector 顺序，绝不把 rerank 失败变成“没有依据”；建议只在日志/技术快照记录错误类型。
- 关闭门禁仍只检查已发布 SOP 的 `scenic_knowledge_hits` 存在，不依赖 rerank 是否成功。

## 4. 检索证据与调用记录

现有 `knowledge_retrieval_snapshots` 不需要新表；把 schema version 从 1 升到 2，并在 `attempts_json`/`references_json` 中增加。下面数值仅示意字段形状，具体分数来自每次运行的实际重排：

```json
{
  "vector_score": 0.734533,
  "rerank_score": 0.974376,
  "score": 0.974376,
  "relevance": 0.974376,
  "rerank_model": "BAAI/bge-reranker-base",
  "rerank_status": "SUCCEEDED",
  "rerank_latency_ms": 122.13
}
```

规则：

- `vector_score` 永远保留 pgvector cosine similarity。
- `rerank_score` 只在 rerank 成功时存在。
- `score`/`relevance` 是最终排序分数，保持既有消费者兼容；成功 rerank 时等于 `rerank_score`，否则等于 `vector_score`。
- `__technical__` 视图保留 `vector_score/rerank_score/rerank_status/rerank_model`；业务视图继续只显示标题、来源、版本、最终 relevance。
- `scenic_knowledge_hits.score` 记录最终排序分数；`_command_retrieve_sop` 的响应/`SOP_RETRIEVED` payload 同时携带 `vector_score` 和 `rerank_score`。由于该路径当前直接调用 `vector_store.query_experience`，实现时必须改为“SQL SOP 真值校验 → 共享 rerank helper → 写 hit/事件”；不能只在通用 retrieval snapshot 中记录重排而让景区 SOP 路径漏掉。如需按 rerank 分数做 SQL 分析，再单独为 `scenic_knowledge_hits` 增加可空列；首版不改变关闭门禁 SQL。
- rerank 模型调用不写 `llm_call_logs`：它是 TEI 推理服务，不是生成式模型调用；rerank 状态进入 retrieval snapshot 和事件技术证据。

## 5. 施工清单

### 代码

| 文件 | 改造 |
| --- | --- |
| `src/memory_palace/tools/embedding_client.py` | 增加 `EmbeddingBackend` Protocol、`TEIEmbeddingBackend`、backend factory；保持 `LocalEmbeddingBackend`/`EmbeddingClient` 公共接口 |
| `src/memory_palace/knowledge/vector_store.py` | 构造器接受协议 backend；默认后端由配置决定；不改变 `query_experience` 签名 |
| `src/memory_palace/knowledge/vector_schema.py` | `index_name`/dimension 保持；TEI cutover 后把 provider/model_version 更新为 `TEI`/`tei-bge-m3-1.9.4-1024-v1`，必须先完成受控 re-embed |
| `src/memory_palace/knowledge/reranking.py` | 新增 `RerankerBackend`、`TEIRerankerBackend`、`NoopRerankerBackend` 和响应校验 |
| `src/memory_palace/knowledge/evidence_backed_retrieval.py` | 注入 reranker；校验后、top-k 前重排；扩展 snapshot schema v2 和降级记录 |
| `src/memory_palace/scenic/operations.py` | 提取共享 rerank helper；`_command_retrieve_sop` 在 PostgreSQL SOP 真值校验后调用同一 helper；`SOP_RETRIEVED` 返回携带 vector/rerank score；门禁条件不变 |
| `src/memory_palace/config/app_settings.py`、`settings.yaml`、`.env.example` | 增加 TEI backend/URL/timeout/batch/rerank 开关；保留本地回滚配置 |
| `scripts/prepare_bge_m3.py` 或新 `scripts/prepare_tei_models.py` | 下载/校验 bge-m3 与 bge-reranker-base 的固定 revision、ONNX 文件和缓存目录 |
| `docs/vector-data-contract.md` | 写明 TEI provider、模型版本、重排证据和空输入/失败语义 |

### 测试

| 测试 | 断言 |
| --- | --- |
| `tests/unit/test_tei_embedding_adapter.py`（新增） | 空列表短路、分片、顺序、1024 维、norm、异常、非 JSON/不完整响应 |
| `tests/unit/test_tei_reranker_adapter.py`（新增） | index 映射、score 降序、非法 index/score、超时失败 |
| `tests/unit/test_vector_search.py` | 保持现有 `query_experience` 返回形状与 1024/租户/source_types 契约 |
| `tests/unit/test_embedding_runtime_budget.py` | 本地 fallback 遗留预算测试保留；TEI 模式不导入 torch |
| `tests/integration/test_evidence_backed_retrieval.py` | rerank 成功改变排序、失败保持 vector order、snapshot v2、租户隔离、关闭门禁不变 |
| `tests/integration/test_scenic_area_operations.py` | `SOP_RETRIEVED` 带 vector/rerank score，关闭门禁仍按 SOP 命中检查 |
| parity/regression 测试（新增） | 本地 vs TEI 分数容差、Top-k/阈值稳定性、真实 TEI 无 Key/服务失败直接失败而非跳过 |

## 6. 分数分布与检索回归

真实 TEI `cpu-1.9.4` 与本地 `LocalEmbeddingBackend` 对照结果：

- 20 条景区处置文档、5 条查询、100 个文档-查询分数。
- 最大绝对分数差：`6.307188781806694e-07`。
- 平均绝对分数差：`2.0672734201643283e-07`。
- p95 绝对分数差：`4.3647216735331895e-07`。
- 5/5 查询 Top-1 一致，5/5 查询 Top-3 完全一致。
- 0.55 阈值命中数量 5/5 一致。
- 对真实 PostgreSQL SOP 索引做 Top-5 检索：5/5 查询 Top-5 ID 完全相同；最大分数差 `1.959269909646011e-07`。

证据：

- `artifacts/tei-migration/score_distribution.json`
- `artifacts/tei-migration/db_retrieval_distribution.json`
- `artifacts/tei-migration/corpus.json`

本次目标回归命令已通过：

```powershell
uv run --no-project --with-requirements requirements.txt python -m pytest -q `
  tests/unit/test_vector_search.py `
  tests/unit/test_embedding_runtime_budget.py `
  tests/integration/test_evidence_backed_retrieval.py
```

结果：目标回归 `28 passed`；本票结束时全量 pytest 也已完成，100% 通过、无失败（当前基线 691 项）。完整切换后仍需增加真实 TEI parity 测试。不得把 TEI 与本地向量做 bitwise equality；使用 `max_abs_diff <= 5e-7`、`cosine >= 0.99999999`，检索断言 top-k ID 和阈值命中不退化。

## 7. 离线准备

固定版本：

- TEI：`ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4`
- 嵌入：`BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`
- 重排：`BAAI/bge-reranker-base` revision `2cfc18c9415c912f9d8155881c133215df768a70`

准备步骤：

1. 用 `snapshot_download(local_dir=...)` 准备独立模型目录，不依赖被中断的 HF hub cache；bge-reranker-base 的 ONNX 文件要走本地目录，避免 `.sync.part` 导致 Candle fallback。
2. 校验文件存在性和 SHA-256；TEI 镜像用 tag + digest 锁定。
3. 预拉取 `cpu-1.9.4`，并预加载 bge-m3 `onnx/model.onnx + onnx/model.onnx.data`、reranker `onnx/model.onnx`。
4. compose 挂载模型目录只读；应用不再挂载本地 torch 模型作为主路径。
5. 启动顺序：TEI ready → 受控 re-embed（同一 index_name，逐批校验 1024 维与来源）→ 更新 provider/model_version → app/worker → 真实检索 smoke。
6. 只有全部 re-embed 行通过维度、来源和数量校验后，`vector_index_versions` 才能标记 TEI `READY`；失败时保留旧 provider/model_version 和旧 app 镜像。

TEI 关键运行参数沿用票 01：

- embedding：`--max-batch-tokens 2048 --max-client-batch-size 16`
- reranker：`--max-batch-tokens 1024 --max-client-batch-size 32`
- backend timeout 由应用侧设置，默认 `20s`；重排超时短于 20s 时可降级，不阻塞事件处置。

## 8. 回滚

- 配置回滚：`EMBEDDING_BACKEND=local` 可在仍保留旧 app 镜像/可选依赖的过渡期恢复本地 torch adapter；正式 TEI 镜像移除了 torch 后，不再承诺运行时切回本地模型。
- 部署回滚：保留上一版 app 镜像。数据库 schema 和 1024 维契约不随 TEI 切换破坏，滚动回滚不要求反向 migration。
- rerank 回滚：`RERANK_BACKEND=none` 或服务失败时保留 pgvector 排序，`rerank_status=DISABLED/FAILED`；不得丢弃候选或伪造分数。
- embedding 回滚：TEI `/embed` 不可用时向量检索返回明确失败；不得返回零向量、空引用或旧的本地模型结果冒充当前结果。业务可继续人工处置，但不能声称知识命中。
- 数据回滚：正式 re-embed 前保留备份/可重建来源；re-embed 使用同一 index_name 和 doc_id 原地更新，只有全部批次校验通过才更新 provider/model_version。如果校验失败，恢复旧 `vector_index_versions` 状态并继续使用旧 app 镜像；绝不在错误版本或半批数据上更新 `READY`。

## 9. 未决/后续

- `TEI_MAX_CLIENT_BATCH_SIZE`、单次 rerank top_n 和超时最终值由票 07 的部署参数锁定。
- 是否在首版为 `scenic_knowledge_hits` 增加独立 rerank 列，待票 09/10 的卷宗/诊断需求确认；当前设计优先复用 JSON 证据，避免无必要 schema 扩张。
- 本票只完成迁移设计与兼容性验证，不修改当前产品的 embedding/rerank 调用路径。

## 10. Review 补强

- 真实 SOP Top-5 证据包含每个 query 的 local/tei doc_id 列表：`artifacts/tei-migration/db_retrieval_distribution.json`；原始查询向量保存在 `artifacts/tei-migration/tei_vectors.json`，生成脚本为 `compare_db_retrieval.py`。
- provider/model_version 不沿用空洞的 `LOCAL` 标签；TEI cutover 的 re-embed 和版本更新是本设计的正式收尾，不是后续可选事项。
- 本票仍未实现 adapter/rerank 代码，因此没有新增 TEI adapter 测试；目标回归验证的是现有路径和真实 TEI 数值兼容性。
