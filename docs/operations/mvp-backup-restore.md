# 企业 MVP 备份、恢复与诊断

`scripts\mvp.cmd` 是 Windows + Docker Desktop 环境的正式运维入口。它只处理
`deploy/docker-compose.yml` 对应的企业 MVP 栈，不适用于旧 `demo_console`。

首次安装、分阶段启动、迁移、运行态验收、日志、升级和停机的完整命令见
[企业 MVP Windows Docker 运维手册](./mvp-windows-docker.md)。本文聚焦备份格式、隔离恢复和恢复验收。

## 前置条件

- Docker Desktop 和 Docker Compose v2 正常运行。
- 源 Compose project 已经存在并运行。
- 恢复时准备一个独立的环境文件；不得把真实 Secret 放入备份目录或提交到仓库。
- 默认备份根目录是 `backups\mvp`，也可以使用专用绝对目录覆盖。

## 查看状态

```powershell
scripts\mvp.cmd status -Project memory-palace-mvp
scripts\mvp.cmd doctor -Project memory-palace-mvp
```

`status` 输出 Docker Engine、Compose、容器、镜像和健康状态。`doctor` 额外检查：

- 每个正式服务是否恰好有一个容器；
- PostgreSQL、Redis 与 Nginx 的实时探针；
- `pg-data`、`redis-data`、`attachment-data` 与 `workspaces-data` 卷；
- 备份磁盘至少有 1 GiB 可用空间。

任何阻断检查失败时，`doctor` 返回非零退出码。

## 创建备份

```powershell
scripts\mvp.cmd backup -Project memory-palace-mvp
scripts\mvp.cmd backup -Project memory-palace-mvp -BackupRoot D:\MVP-Backups
```

备份在同一事务边界内完成 PostgreSQL 逻辑备份：短暂停止属于该 project 的运行中 App 容器，
PostgreSQL 保持运行并执行一致性 `pg_dump`；完成或失败后脚本恢复此前运行的容器。

每个备份目录包含：

| 文件 | 内容 |
|---|---|
| `postgres.dump` | PostgreSQL custom-format 逻辑备份 |
| `attachment-data.tar.gz` | 现场附件与证据文件卷 |
| `workspaces-data.tar.gz` | Agent 工作区与运行中间产物卷 |
| `manifest.json` | schema、来源 project、Git 状态、Compose 哈希、Docker/镜像版本、文件大小和 SHA-256 |

脚本先写入同级 `.partial` 目录，所有文件和校验完成后才原子重命名为最终 Backup ID。
当前备份格式为 `memory-palace-mvp-backup/v2`。备份不包含 `.env`、JWT Secret、数据库密码或
DeepSeek API Key；Embedding 模型属于运行依赖，不含业务凭据。

`manifest.json` 中的 SHA-256 用于发现损坏或误修改，不是数字签名。备份仍包含企业业务数据，
必须放在受访问控制的磁盘或加密备份介质中；默认 `backups\` 目录已被 Git 忽略。

## 恢复到新 Compose project

推荐先从 `.env.example` 创建一个不入库的恢复环境文件，并使用测试渠道凭据：

```powershell
scripts\mvp.cmd restore `
  -BackupId mp-memory-palace-mvp-20260728t120000z-ab12cd34 `
  -TargetProject memory-palace-restore-01 `
  -ConfirmTarget memory-palace-restore-01 `
  -EnvFile D:\MVP-Secrets\restore.env `
  -TargetSecretsVolume memory-palace-restore-01-secrets `
  -TargetHttpPort 18080
```

恢复过程会验证：

- Backup ID 只能是备份根目录的直接子目录，不能包含路径跳转；
- 备份根目录、备份目录和所有输入文件不能是符号链接或 reparse point；
- Manifest schema、Backup ID、固定文件名和 SHA-256；
- Compose 文件与备份时的哈希一致；
- `ConfirmTarget` 必须与目标 project 大小写完全一致。
- `TargetSecretsVolume` 必须精确为 `<TargetProject>-secrets`，脚本会创建或验证其为空，并以
  进程级环境变量覆盖 EnvFile 中可能存在的全局 Secret 卷配置。

恢复栈不会复用来源栈的 `memory-palace-secrets`。仅恢复数据服务时，目标专属 Secret 卷保持为空；
使用 `-StartApplication` 时，脚本只写入一个非敏感的禁用占位符，并把恢复栈的 DeepSeek 地址强制
指向容器本机不可用端口。这样可以验证登录、查询和恢复完整性，同时不会携带来源环境的 API Key、
向外发送 LLM 请求或修改来源栈 Secret 卷。若要把恢复栈提升为可调用 LLM 的独立环境，应在恢复
验收后按变更流程为该目标卷注入目标环境自己的 Key 并重新创建 App，不能改回来源卷。

默认只启动 PostgreSQL 与 Redis，避免恢复出的未完成任务使用真实渠道产生
外部动作。确认恢复环境使用测试凭据后，可以显式启动完整栈：

```powershell
scripts\mvp.cmd restore `
  -BackupId mp-memory-palace-mvp-20260728t120000z-ab12cd34 `
  -TargetProject memory-palace-restore-01 `
  -ConfirmTarget memory-palace-restore-01 `
  -EnvFile D:\MVP-Secrets\restore.env `
  -TargetSecretsVolume memory-palace-restore-01-secrets `
  -TargetHttpPort 18080 `
  -StartApplication
```

## 覆盖保护

如果目标 project 已有任意容器、网络或卷，恢复会拒绝执行。只有同时满足下面两个条件
才允许删除目标 project 的 Compose 资源和命名卷：

1. `-ConfirmTarget` 与目标 project 完全一致；
2. 显式传入 `-Force`。

```powershell
scripts\mvp.cmd restore `
  -BackupId <backup-id> `
  -TargetProject memory-palace-restore-01 `
  -ConfirmTarget memory-palace-restore-01 `
  -EnvFile D:\MVP-Secrets\restore.env `
  -TargetSecretsVolume memory-palace-restore-01-secrets `
  -Force
```

`-Force` 也用于确认恢复到来源 project，或确认使用与 Manifest 哈希不同的 Compose 文件。
它不会绕过路径、Manifest、校验和或精确目标确认。

## 独立恢复验收

1. 使用新的 Compose project 和独立 HTTP 端口恢复。
2. 使用 `status` 检查数据服务健康。
3. 使用只读 SQL 核对场馆、会话、任务、审批和知识记录数量。
4. 启动完整栈后验证 pgvector 检索、登录和事件查询；首次向量检索应直接命中已恢复的
   `embedding-cache`，不得触发在线模型下载。
5. 完整栈启动后执行 `doctor`，保存输出和 `manifest.json` 作为恢复证据。默认仅恢复数据服务时，
   App 与 Nginx 按设计保持停止，此时不要把完整 `doctor` 的服务检查当作失败证据。

不要把对现有 UAT project 的 `-Force` 恢复作为首次演练。首次恢复必须使用新的 project。

## 与升级流程的关系

`scripts\mvp.cmd upgrade` 会在拉取、构建、迁移或重新创建任何服务之前调用同一个 `backup` 流程。
只有 Manifest、三个制品、大小、SHA-256 和平台备份记录全部完成后，升级才会继续。升级失败不会
自动删除数据或 Secret；脚本会输出一个新的隔离恢复 project、独立 Secret 卷和端口对应的
`restore` 命令。应先按本文的独立恢复步骤验收，再决定回退版本和流量切换。

正式升级还会拒绝脏 Git worktree，并将 HEAD 记录为构建镜像标签。`-AllowDirtyBuild` 仅供内部开发
环境验证，不得用于客户发布；脏构建的备份 Manifest 会明确保留 `dirty=true` 证据。
