# 企业 MVP Windows Docker 运维手册

`scripts\mvp.cmd` 是 Memory Palace OS 企业 MVP 在 Windows + Docker Desktop 上的正式运维入口。
它固定使用 `deploy/docker-compose.yml`，覆盖安装、启动、状态、迁移、验收、备份、恢复、日志、
升级、App 单服务重启、停机和诊断，不用于旧 Demo 栈。

## 安全模型

- 每个需要解析部署配置的命令都必须显式传入 `-EnvFile`。脚本只把文件路径交给 Docker Compose，
  不读取或回显其中的密码、Token 或 Key。
- `install/start/migrate/verify/logs/upgrade/restart-app/stop` 锁定仓库正式 `deploy/docker-compose.yml`；
  `-ComposeFile` 覆盖只保留给带 Manifest 兼容校验的既有备份/恢复流程。
- DeepSeek API Key 只存放在 Docker external volume 的 `deepseek_api_key` 文件中，不写入 EnvFile、
  仓库、镜像层、备份或命令行参数。
- `-SecretsVolume` 显式指定正式栈使用的 external volume。整个生命周期必须持续使用同一个卷名。
- `stop` 不删除容器、数据卷、网络或 external secrets；本入口没有隐式的卸载或销毁命令。
- `upgrade` 不自动回滚或删除数据。升级失败时保留升级前备份，并输出隔离恢复命令。
- `install` 和 `upgrade` 默认要求干净 Git worktree，并把完整 HEAD 注册为 App 镜像版本标签。
`-AllowDirtyBuild` 只允许本机内部开发，客户发布和正式变更不得使用。

Docker Desktop 无法访问镜像仓库、但所有固定版本镜像已经缓存在本机时，可对 `install` 或 `upgrade`
显式增加 `-Offline`。该开关只跳过 `pull`，不会改变 Compose、镜像版本、迁移、健康检查或备份门禁；
缺少任何基础镜像时构建会直接失败。

## 首次部署

先在仓库外准备正式环境文件。可以从 `.env.example` 复制字段结构，但必须替换所有占位值，
限制文件访问权限，并确保它不会被 Git 跟踪。以下示例中的路径和卷名需要按实际环境调整：

```powershell
$MvpProject = "memory-palace-mvp"
$MvpEnvFile = "D:\MemoryPalace\config\production.env"
$MvpSecretsVolume = "memory-palace-mvp-secrets"

scripts\mvp.cmd install `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

`install` 执行以下操作：

1. 检查 Docker Engine 和 Docker Compose v2；
2. 创建或复用指定的 external secrets volume；
3. 拉取固定版本的 PostgreSQL、Redis、Nginx 和备份辅助镜像；
4. 从当前获批 Git HEAD 构建 App 镜像，并以 HEAD 短哈希注册不可混淆的本地版本标签。

若 worktree 存在未提交或未跟踪改动，正式安装会在构建前失败。内部联合开发确需验证工作树时可
显式加 `-AllowDirtyBuild`，生成的镜像会带 `-dirty` 标签；该开关不得进入客户发布命令、变更单或
交付手册。

`install` 不会生成、复制或伪造 DeepSeek Key。首次启动前，通过安全交互脚本写入同一个卷：

```powershell
scripts\set_deepseek_secret.ps1 -VolumeName $MvpSecretsVolume
```

该脚本使用 `SecureString` 交互读取 Key，并将其原子写入 external volume。不要把 Key 作为普通字符串
保存在终端历史、文档或工单中。为了让手工 Compose 操作也使用同一卷，EnvFile 中的
`MEMORY_PALACE_SECRETS_VOLUME` 应与 `-SecretsVolume` 保持一致。

## 启动与迁移

```powershell
scripts\mvp.cmd start `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

`start` 按固定阶段执行，任一阶段失败都会返回非零退出码：

1. 验证 external volume 和非空 `deepseek_api_key`，但不读取文件内容；
2. 启动 PostgreSQL、Redis 与 Nginx，并逐一等待容器健康；缺失 healthcheck 直接失败；
3. 运行幂等 PostgreSQL 初始化和管理员身份引导，记录 `mvp_schema_migrations` 版本；
4. 启动 App 并等待健康；
5. 启动 Nginx 并等待健康。

需要单独重跑数据库迁移时：

```powershell
scripts\mvp.cmd migrate `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

`migrate` 只确保 PostgreSQL 运行，然后通过 App 镜像调用仓库正式入口
`init_database(PostgresDBClient())`。DDL 使用 `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`，
可重复执行；每次成功执行都会更新当前脚本版本的迁移记录。

## 状态、诊断与验收

```powershell
scripts\mvp.cmd status -Project $MvpProject
scripts\mvp.cmd doctor -Project $MvpProject -BackupRoot "D:\MemoryPalace\backups"
scripts\mvp.cmd verify `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume `
  -BackupRoot "D:\MemoryPalace\backups"
```

- `status` 显示 Docker/Compose 版本及五个正式服务的容器、状态、健康和镜像。
- `doctor` 检查服务唯一性、容器健康、三个运行依赖探针、关键数据卷和备份磁盘空间。
- `verify` 先执行完整 `doctor`，再检查 external Secret 文件存在、App `/health`、Nginx
  `/health` 以及正式客户端 `/admin/` 可达。它不请求登录凭据，也不打印响应正文。

`verify` 是部署级冒烟验收，不替代逐功能 UAT。版本交付仍需运行正式客户端认证、Agent、审批、
知识、Persona、Watcher、SOP、配置和恢复旅程。

### App 单服务重启

```powershell
scripts\mvp.cmd restart-app `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

`restart-app` 只调用 Compose `restart app`，等待 App 恢复健康，并核对 PostgreSQL、Redis 与 Nginx 的
容器 ID、进程 ID 和启动时间均未变化。命令输出 App 重启前后的运行标识；
随后在 `/admin/diagnostics` 核对启动恢复记录、pending claim 和 ACK。该命令不重启数据服务、不清卷、
不重建镜像，也不重新注入 Secret。

## 日志

默认只读取每个服务最近 200 行并立即退出：

```powershell
scripts\mvp.cmd logs `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

指定服务、行数并显式持续跟随：

```powershell
scripts\mvp.cmd logs `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume `
  -Service app `
  -Tail 500 `
  -Follow
```

`-Service` 可重复指定 `app`、`postgres`、`redis`、`nginx`。`-Tail` 范围是
1–5000。输出会对常见 Password、Token、Secret、API Key、Bearer 值和 `sk-` Key 做防御性
脱敏；这不是在应用日志中记录凭据的许可，日志仍可能包含受保护的业务数据，应按生产数据管理。

## 备份与恢复

```powershell
scripts\mvp.cmd backup `
  -Project $MvpProject `
  -BackupRoot "D:\MemoryPalace\backups"
```

恢复同时支持 PRD 的位置参数和原有命名参数，两种写法等价：

```powershell
scripts\mvp.cmd restore <backup-id> ...
scripts\mvp.cmd restore -BackupId <backup-id> ...
```

恢复必须使用精确目标确认、独立目标 Secret 卷，并默认只启动数据服务。完整的 Manifest、校验和、
覆盖保护、隔离 Secret 和恢复验收说明见 [企业 MVP 备份、恢复与诊断](./mvp-backup-restore.md)。

## 升级

在已健康运行的正式栈上执行：

```powershell
scripts\mvp.cmd upgrade `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume `
  -BackupRoot "D:\MemoryPalace\backups"
```

`upgrade` 的固定顺序是：

1. 创建并完整校验升级前备份；
2. 拉取固定依赖镜像并构建当前交付源码的 App 镜像；
3. 更新数据依赖容器并等待健康；
4. 执行幂等 PostgreSQL 迁移；
5. 强制重新创建 App 和 Nginx；
6. 执行完整 `verify`。

升级同样要求干净 Git worktree，并在构建后输出完整 Release HEAD、版本化镜像标签和镜像 ID。
内部开发可显式使用 `-AllowDirtyBuild`，正式客户升级禁止使用。

可以用 `-BackupId` 为变更单指定可追踪的安全 ID；不指定时自动生成。升级失败不会执行
`down --volumes`、删除 external secrets 或自动恢复。若备份已完成，脚本会输出一条可直接执行的
隔离恢复命令，例如：

```powershell
scripts\mvp.cmd restore `
  -BackupId <upgrade-backup-id> `
  -BackupRoot "D:\MemoryPalace\backups" `
  -TargetProject memory-palace-mvp-rollback `
  -ConfirmTarget memory-palace-mvp-rollback `
  -EnvFile $MvpEnvFile `
  -TargetSecretsVolume memory-palace-mvp-rollback-secrets `
  -TargetHttpPort 18081
```

先在隔离项目中验收数据，再重新部署上一版本源码/镜像并按变更流程切换流量。不要在未验证恢复
之前覆盖当前正式 project，也不要把来源 Secret 卷挂到恢复项目。

## 停机

```powershell
scripts\mvp.cmd stop `
  -Project $MvpProject `
  -EnvFile $MvpEnvFile `
  -SecretsVolume $MvpSecretsVolume
```

`stop` 只调用 Compose `stop`。PostgreSQL、Redis、日志、附件与工作区数据卷、
容器配置和 external secrets 均保留。再次执行 `start` 会复用原数据和 Key，并重新执行幂等迁移。

## 命令清单

| 命令 | EnvFile | 主要结果 |
|---|---:|---|
| `install` | 必需 | 拉取/构建镜像，准备空 external Secret 卷 |
| `start` | 必需 | 分阶段启动、迁移并等待健康 |
| `status` | 不需要 | 查看 Docker 与服务状态 |
| `migrate` | 必需 | 幂等执行正式 PostgreSQL 初始化 |
| `verify` | 必需 | Doctor、健康探针、正式客户端可达验收 |
| `backup` | 不需要 | 创建 v2 数据与向量完整备份 |
| `restore` | 必需 | 校验并隔离恢复到明确目标 |
| `logs` | 必需 | 有限 tail；显式 Follow；输出脱敏 |
| `upgrade` | 必需 | 备份、构建/拉取、迁移、重建、验收 |
| `restart-app` | 必需 | 仅重启 App，校验其他服务未变化并等待健康 |
| `stop` | 必需 | 停止容器并保留全部持久数据和 Secret |
| `doctor` | 不需要 | 运行依赖、卷和备份空间诊断 |

## 已知边界

- App 镜像从本地获批 Git HEAD 构建并注册 HEAD 标签；脚本拒绝脏工作树。`-AllowDirtyBuild` 仅为
  内部联合开发保留，不能作为客户发布例外。
- 数据库迁移是向前兼容、幂等初始化，不提供自动逆向 DDL。数据回退以升级前备份的隔离恢复为准。
- `verify` 验证部署可用性和正式客户端可达，不包含带真实账号的业务功能验收。
- 日志脱敏是兜底机制，无法替代应用侧禁止记录凭据和日志访问控制。
- 本入口没有删除数据卷或 Secret 卷的命令；退役环境必须走单独审批和人工确认流程。
