# Memory Palace OS 交付与复现说明

更新时间：2026-09-29

这份说明面向接手本项目的 Claude Code、Codex 或工程师。压缩包包含源码、Docker 部署配置、数据集、evals、单元/集成测试和已保存的验证证据。运行时凭据、数据库卷、模型缓存和依赖缓存不放入源码包，需要在接收机器上重新配置。

## 1. 运行边界

推荐使用 Windows 10/11 + Docker Desktop（启用 Linux containers 和 Compose v2），并安装 Git、PowerShell、`uv`。也可以在 Linux/macOS 上使用等价的 Docker Compose 命令。建议至少准备 8 GB 可用内存、20 GB 可用磁盘；首次下载 `BAAI/bge-m3` 模型还需要额外缓存空间。Docker 镜像和模型需要网络下载；Node/pnpm 与 Python 应用依赖由 Docker 构建安装，运行 evals 时由 `uv` 安装。

版本以仓库中的锁定文件和 Dockerfile 为准：Python 3.11、Node 24、pnpm 11、TEI CPU 1.9.4，以及 `requirements.lock` / `frontend/pnpm-lock.yaml`。不要在接手时自行升级依赖；如需升级，先单独建立变更并重新跑测试与 evals。

## 2. 首次配置

在项目根目录执行：

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force C:\memory-palace-models\huggingface | Out-Null
$env:BGE_M3_CACHE_DIR = 'C:\memory-palace-models\huggingface'
scripts\scenic.ps1 prepare-model -ModelCache $env:BGE_M3_CACHE_DIR
```

编辑 `.env`，至少替换以下值：

- `BGE_M3_CACHE_DIR`：模型缓存的绝对路径；该目录必须包含 `BAAI/bge-m3`。
- `MEMORY_PALACE_SECRETS_VOLUME=memory-palace-package-secrets`：与下面写入密钥时的卷名保持一致。
- `POSTGRES_PASSWORD`、`ADMIN_PASSWORD`、`MEMORY_PALACE_JWT_SECRET`：每台机器生成新的强随机值。
- `ADMIN_USERNAME`：交付环境管理员账号。

DeepSeek API key 和员工共享密码写入 Docker secret volume，不要写进 `.env`、Git 或聊天记录：

```powershell
scripts\set_deepseek_secret.ps1 -VolumeName memory-palace-package-secrets
scripts\set_scenic_account_secret.ps1 -VolumeName memory-palace-package-secrets
```

## 3. 启动正式本地链路

```powershell
$env:BGE_M3_CACHE_DIR = 'C:\memory-palace-models\huggingface'
scripts\scenic.ps1 start -ModelCache $env:BGE_M3_CACHE_DIR
scripts\scenic.ps1 doctor -ModelCache $env:BGE_M3_CACHE_DIR
Invoke-WebRequest http://localhost:8090/health
```

本包是当前工作树快照，不携带 `.git`。`scripts/mvp.cmd install` 需要 Git HEAD，不能在刚解压的目录直接运行；上面的 `scenic.ps1` 路径可直接从源码构建并启动默认 Docker Compose 栈。需要正式发布流程时，先将审定的源码纳入版本库，再按 `README.md` 使用 `mvp.cmd`。

启动后访问：

- 管理后台：`http://localhost:8090/admin/`
- 员工助手：`http://localhost:8090/assistant/`
- 企微流程模拟器：`http://localhost:8090/simulator/wecom/`
- 健康检查：`http://localhost:8090/health`

如果使用不同端口，在 `.env` 中修改 `HTTP_PORT`，并以实际端口替换上面的地址。

## 4. 导入项目数据集

项目中的可移植数据集位于 `evals/scenic_agent/` 和 `artifacts/knowledge/`。展示用知识、事件、任务、访谈、经验卡和巡检策略通过正式 HTTP API 创建，不直接写数据库：

```powershell
$env:MEMORY_PALACE_UAT_BASE_URL = 'http://127.0.0.1:8090'
$env:ADMIN_USERNAME = '<与 .env 相同的管理员账号>'
$env:ADMIN_PASSWORD = '<与 .env 相同的管理员密码>'
uv run --no-project --with-requirements requirements.txt `
  python -m scripts.unified_agent_uat.cli `
  showcase-seed --sections sourced
```

该命令可重复执行。它会复用同一来源 ID、事件 ID、任务会话 ID 和巡检策略键；只有仍保持旧种子文本的知识记录会被更新。不要直接导入本机的 `data/*.db` 或日志目录。

## 5. 运行测试与 evals

先运行不需要外部模型的契约和单元测试：

```powershell
uv run --no-project --with-requirements requirements.txt pytest -q
uv run --no-project --with-requirements requirements-eval.txt `
  python evals/scenic_agent/run_deepeval.py --mode contract `
  --report artifacts/scenic-agent-eval/contract-report-local.json
```

需要真实 DeepSeek 凭据的 live eval：

```powershell
$env:DEEPSEEK_API_KEY = '<从 secret 管理器注入>'
uv run --no-project --with-requirements requirements-eval.txt `
  python evals/scenic_agent/run_deepeval.py --mode live --tier fast `
  --report artifacts/scenic-agent-eval/live-fast-report-local.json
```

`golden_*`、`sample_100_cases.json`、`corpus_cases.json` 和 failure replay 数据都随包提供。live eval 的模型响应、费用和延迟取决于接收机器的网络、账号配额和供应商当时的模型版本，因此不能把本地响应文件当作新的金标准提交。

## 6. 给 Claude Code / Codex 的启动提示

把下面文字作为接手后的第一条任务消息，或让工具先读取 `AGENTS.md` / `CLAUDE.md`：

```text
你正在接手 Memory Palace OS。先阅读 REPRODUCE.md、README.md、.env.example、deploy/docker-compose.yml、evals/scenic_agent/ 和 tests/，再检查 git status。不要读取或输出 .env、Docker secret、数据库卷、日志中的凭据。优先使用 Docker Compose 和仓库内的锁定依赖；不要自行升级版本。修改前先说明影响范围，修改后至少运行受影响的 pytest、契约 eval 和 git diff --check。数据集通过正式 API 或已有导入脚本处理，不直接写 data/*.db。保留当前工作树中与任务无关的改动。
```

## 7. 不随包携带的本机状态

`.env`、`.venv`、`frontend/node_modules`、Docker named volumes、`data/*.db`、日志、向量数据库、模型缓存和临时构建缓存均不进入交付包。它们可能包含凭据、个人数据、机器路径或不可移植的二进制状态；接收方按本说明重建可得到同一应用链路和可重播数据集，但不会自动拥有本机运行历史、账号密码或完全相同的实时模型输出。若确实要迁移运行历史，需另做经授权、脱敏并加密的数据库备份与恢复。
