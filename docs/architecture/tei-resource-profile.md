# TEI 服务资源画像与镜像锁定（票 01）

状态：已实测（2026-09-17）

## 结论

- 锁定镜像：`ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4`。
- `docker manifest inspect` 通过；manifest list digest：
  `sha256:2538ea1c9640d3763b15af668039d24172d063b42337b0c27796fc2be180c78d`。
  amd64 平台 digest：`sha256:8419f533857b503ebf6ec292a95d4f1cf9c0464ac8b8abeef39518cf110e5726`。
- 6GB WSL 下可以同时运行两个 TEI 进程，但配置必须显式限制：
  - 嵌入：`BAAI/bge-m3`，`--max-batch-tokens 2048`。
  - 重排：`BAAI/bge-reranker-base`，`--max-batch-tokens 1024`。
  - TEI 会用同一镜像启动两次；一个进程只承载一个模型，不能把嵌入和重排放进同一个 TEI 进程。
- `bge-m3` 使用默认/更高 batch token 会 OOM；`16384` 和 `8192` 均实测 `OOMKilled`。6GB 下不能直接使用 TEI 默认的 16384。
- 两个模型同时常驻时，RSS 约 4.57GiB，6GB VM 只剩约 0.55GiB 可用内存（另有约 0.79GiB swap 使用）。因此：
  - 业务应用迁移后必须去掉进程内 torch/sentence-transformers，保持约 0.3GiB 级别；
  - Hatchet、Jaeger 不应与两个 TEI 模型同时常驻在 6GB；常驻它们应评估 8GB。
- `LocalEmbeddingBackend` 的接口不需要改变；嵌入仍由 HTTP adapter 返回 1024 维、归一化向量。TEI 与本地 PyTorch 不是逐位一致，必须用 float32 容差和检索回归验证，不能做 bitwise equality 断言。
- 空输入是契约差异：本地 `embed_batch_sync([])` 返回 `[]`；TEI `/embed` 与 `/rerank` 对空数组返回 HTTP 400。adapter 必须在发 HTTP 前短路空输入。

## 环境与命令

测量时：

- WSL：`.wslconfig` 为 `memory=6GB`、`autoMemoryReclaim=gradual`。
- Docker：Docker Desktop 4.88.1，Server 29.7.2，Linux x86_64，12 CPU，Docker 可用内存 `6,212,431,872` bytes（约 5.79GiB）。
- 其他项目容器、景区 PostgreSQL/Redis/Nginx 保持运行；景区 app 容器在 TEI 测量期间停止，以释放原来的 torch 模型常驻内存。

锁定检查：

```powershell
docker manifest inspect ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4
```

嵌入服务实测命令：

```powershell
docker run -d --name mp-tei-embedding `
  -p 18000:80 --cpus 4 `
  -v 'D:/memory-palace-models/huggingface:/data' `
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4 `
  --model-id BAAI/bge-m3 `
  --huggingface-hub-cache /data/hub `
  --tokenization-workers 4 `
  --max-concurrent-requests 32 `
  --max-batch-tokens 2048 `
  --max-client-batch-size 16
```

TEI 最终把 `max_batch_requests` 强制为 8，即使显式传 `--max-batch-requests 1` 也不生效；不要把该参数当作内存上限。

重排服务实测命令：

```powershell
# 通过 snapshot_download(local_dir=...) 先准备含 model.onnx 的本地目录；
# 不要复用被中断后留下 .sync.part 的 HF cache，否则 ONNX 可能退化为 Candle。
docker run -d --name mp-tei-reranker `
  -p 18001:80 --cpus 4 `
  -v 'D:/memory-palace-models/tei:/data' `
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4 `
  --model-id /data/bge-reranker-base-onnx `
  --tokenization-workers 4 `
  --max-concurrent-requests 32 `
  --max-batch-tokens 1024 `
  --max-client-batch-size 32
```

模型版本：

| 模型 | revision | 后端 |
| --- | --- | --- |
| `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` | ONNX ORT |
| `BAAI/bge-reranker-base` | `2cfc18c9415c912f9d8155881c133215df768a70` | ONNX ORT |

## 内存与冷启动

冷启动测量方法：停止两个 TEI 容器后分别或同时 `docker start`，从 start 返回到 `/health` 返回 200 计时。

| 场景 | 秒 |
| --- | ---: |
| 只启动嵌入 | 15.742 |
| 只启动重排 | 5.743 |
| 同时启动两者 | 19.320 |

内存测量方法：`docker stats --no-stream` 查看 RSS，容器内读取 `/sys/fs/cgroup/memory.current`、`memory.peak`，再用临时 Alpine 容器执行 `free -m`。

| 项目 | 结果 |
| --- | ---: |
| 嵌入 RSS | 2.424 GiB |
| 重排 RSS | 2.143 GiB |
| 两者合计 RSS | 4.567 GiB |
| 嵌入 cgroup current / peak | 2.633 / 2.929 GiB |
| 重排 cgroup current / peak | 2.307 / 2.999 GiB |
| VM `free -m` | total 5925, used 5226, available 555, swap used 791 MiB |

结论：两个模型本身在 6GB 内，但没有足够空间再放当前包含 torch 的 app 容器；迁移后 app 约 0.3GiB 时仍非常紧，任何常驻 Hatchet/Jaeger 或更高重排模型都需要 8GB。

## 延迟

嵌入 `/embed`：每个 batch size 使用 3 次预热 + 10 次测量；输入为短中文景区处置文本。

| batch size | min ms | p50 ms | p95 ms | max ms | mean ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 78.18 | 87.90 | 99.03 | 99.03 | 88.90 |
| 8 | 390.84 | 418.85 | 492.36 | 492.36 | 433.68 |
| 16 | 753.62 | 811.40 | 890.63 | 890.63 | 814.13 |

重排 `/rerank`：每个候选数使用 3 次预热 + 10 次测量。

| candidates | min ms | p50 ms | p95 ms | max ms | mean ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 107.29 | 122.13 | 138.89 | 138.89 | 123.06 |
| 20 | 366.45 | 398.29 | 470.25 | 470.25 | 405.81 |

重排 ONNX 与 Candle fallback 对比：Candle fallback 在 5/20 候选上的 p50 约为 237/939 ms，明显慢于 ONNX 的 122/398 ms。生产准备必须显式准备 ONNX 文件，或在性能预算上接受 Candle 退化。

## 输出契约对照

| 契约项 | `LocalEmbeddingBackend` | TEI | 结论 |
| --- | --- | --- | --- |
| 维度 | 1024 | 1024 | 对齐 |
| 归一化 | `normalize_embeddings=True` | 返回向量 norm ≈ 1 | 对齐；batch 16 norm 最大绝对误差 `9.39e-9` |
| 批量顺序 | 输入顺序 | 输入顺序 | 对齐 |
| 空输入 | 直接返回 `[]` | HTTP 400 | adapter 必须短路空输入 |
| 文本截断 | 先截到 8192 字符 | 受 `max-batch-tokens`/`auto-truncate` 控制 | 需 adapter 明确截断策略；不能假定逐字符等价 |
| 重排 | 现有 `LocalEmbeddingBackend` 不提供 | `/rerank` 返回按 score 降序的 `{index, score}` | 重排应放在检索层，单独 adapter，不扩张 embedding 接口 |
| 向量逐位一致 | — | — | 不一致；不能做 bitwise equality |

同一 4 条中文输入（共 4096 个分量）的本地 PyTorch 与 TEI ONNX 对照：

- 最大绝对差：`2.307011222821287e-07`
- bit-equal 分量：`46 / 4096`（`1.123%`）
- cosine similarity：所有样本约 `0.999999999998` 到 `1.000000000000`
- 结论：数值语义和检索可用性对齐，但不是逐位对齐。票 03 的迁移测试应使用 `max_abs_diff <= 5e-7`、`cosine >= 0.99999999`，并保留现有向量检索的 top-k/分数分布回归。

## 已知失败与限制

- `BAAI/bge-m3` + `--max-batch-tokens 16384`：warmup 阶段 `OOMKilled=1`。
- `BAAI/bge-m3` + `--max-batch-tokens 8192` + `--max-batch-requests 1`：仍 `OOMKilled=1`；TEI 实际强制 batch requests=8。
- `bge-reranker-base` 的 HF hub cache 在一次中断重启后出现 `.sync.part`，ONNX 无法解析并退化到 Candle；`snapshot_download(local_dir=...)` 后本地 ONNX 目录可稳定启动。
- 本轮 `max-batch-tokens=2048` 覆盖当前最长 SOP（实测约 1785 tokens），但不等于模型原生 8192 token 上下文；需要完整长上下文时必须重新做 8GB 预算。
- 本轮未测量真正清空 OS page cache 后的磁盘冷启动，只测了进程/模型加载冷启动；缓存准备与磁盘冷启动属票 07 的离线准备范围。

## 证据

- [evidence.json](/D:/Documents/memory-palace-os/artifacts/tei-profile/evidence.json)
- [parity.json](/D:/Documents/memory-palace-os/artifacts/tei-profile/parity.json)
- [local_vectors.json](/D:/Documents/memory-palace-os/artifacts/tei-profile/local_vectors.json)