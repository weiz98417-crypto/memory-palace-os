[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "install", "start", "status", "migrate", "bootstrap-uat", "verify", "backup",
        "restore", "logs", "upgrade", "restart-app", "stop", "doctor", "help"
    )]
    [string]$Command = "help",

    [string]$Project = "memory-palace-mvp",
    [string]$TargetProject,
    [Parameter(Position = 1)]
    [string]$BackupId,
    [string]$BackupRoot,
    [string]$ComposeFile,
    [string]$EnvFile,
    [string]$SecretsVolume = "memory-palace-secrets",
    [string]$ConfirmTarget,
    [string]$TargetSecretsVolume,
    [ValidateRange(1, 65535)]
    [int]$TargetHttpPort = 18080,
    [ValidateRange(1, 5000)]
    [int]$Tail = 200,
    [ValidateSet("app", "postgres", "redis", "chromadb", "nginx")]
    [string[]]$Service,
    [switch]$Force,
    [switch]$StartApplication,
    [switch]$Follow,
    [switch]$AllowDirtyBuild,
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$ScriptVersion = "2.1.0"
$ManifestSchema = "memory-palace-mvp-backup/v2"
$ArchiveImage = "alpine:3.20.10"
$PostgresArtifactName = "postgres.dump"
$ChromaArtifactName = "chroma-data.tar.gz"
$EmbeddingArtifactName = "embedding-cache.tar.gz"
$ManifestName = "manifest.json"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $ProjectRoot "backups\mvp"
}
if (-not $ComposeFile) {
    $ComposeFile = Join-Path $ProjectRoot "deploy\docker-compose.yml"
}

function Show-Usage {
    Write-Host @"
Memory Palace OS MVP operations

  scripts\mvp.cmd install -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>] [-AllowDirtyBuild] [-Offline]
  scripts\mvp.cmd start   -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd status  -Project <project>
  scripts\mvp.cmd migrate -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd bootstrap-uat -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd verify  -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd backup  -Project <source-project> [-BackupRoot <directory>]
  scripts\mvp.cmd restore <backup-id> -TargetProject <target-project> `
      -EnvFile <path> -ConfirmTarget <target-project> `
      -TargetSecretsVolume <target-project-secrets> [-TargetHttpPort 18080] `
      [-Force] [-StartApplication]
  scripts\mvp.cmd logs    -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>] [-Tail 200] [-Follow]
  scripts\mvp.cmd upgrade -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>] [-BackupRoot <directory>] [-AllowDirtyBuild] [-Offline]
  scripts\mvp.cmd restart-app -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd stop    -EnvFile <path> [-Project <project>] [-SecretsVolume <volume>]
  scripts\mvp.cmd doctor  -Project <project> [-BackupRoot <directory>]

Restore never accepts an arbitrary archive path. BackupId must name a direct child
of BackupRoot. Exact target confirmation is always required. Existing target
resources additionally require -Force. By default restore starts only PostgreSQL,
Redis, and ChromaDB; -StartApplication explicitly enables App and Nginx startup.
Deployment commands default to external volume 'memory-palace-secrets'; use the
same explicit -SecretsVolume for install, start, migrate, verify, logs, upgrade,
restart-app, and stop when the deployment uses a project-specific volume.
Use -Offline only when every pinned base/runtime image is already present locally;
the build fails without changing versions if any required image is missing.
"@
}

function Test-PathEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    return [string]::Equals(
        $Left.TrimEnd('\', '/'),
        $Right.TrimEnd('\', '/'),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Get-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Assert-ProjectName {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ParameterName
    )

    if ($Name -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') {
        throw "$ParameterName must be 3-63 lowercase letters, digits, underscores, or hyphens."
    }
}

function Assert-DockerVolumeName {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ParameterName
    )

    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{1,254}$') {
        throw "$ParameterName must be a valid Docker volume name."
    }
}

function Assert-BackupId {
    if (-not $BackupId -or $BackupId -notmatch '^[a-z0-9][a-z0-9._-]{2,127}$' -or $BackupId -in @(".", "..")) {
        throw "BackupId must be a safe name for one direct child of BackupRoot; path separators and traversal are forbidden."
    }
}

function Resolve-ExistingFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ParameterName
    )

    $fullPath = Get-FullPath -Path $Path
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "$ParameterName does not exist or is not a file: $fullPath"
    }
    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "$ParameterName must not be a symbolic link or reparse point: $fullPath"
    }
    return $item.FullName
}

function Assert-DeploymentParameters {
    Assert-ProjectName -Name $Project -ParameterName "Project"
    if (-not $EnvFile) {
        throw "EnvFile is required; provide the explicit deployment configuration file for this command."
    }
    Resolve-ExistingFile -Path $EnvFile -ParameterName "EnvFile" | Out-Null
    $resolvedComposeFile = Resolve-ExistingFile -Path $ComposeFile -ParameterName "ComposeFile"
    $officialComposeFile = Get-FullPath -Path (Join-Path $ProjectRoot "deploy\docker-compose.yml")
    if (-not (Test-PathEqual -Left $resolvedComposeFile -Right $officialComposeFile)) {
        throw "Deployment lifecycle commands require the official ComposeFile '$officialComposeFile'; overrides are reserved for compatibility-checked backup and restore operations."
    }
}

function Resolve-SafeBackupRoot {
    param([switch]$Create)

    $fullPath = Get-FullPath -Path $BackupRoot
    if ($fullPath -match '[,\r\n]') {
        throw "BackupRoot contains characters that cannot be safely passed to Docker mounts."
    }

    $fileSystemRoot = [System.IO.Path]::GetPathRoot($fullPath)
    $rejectedRoots = @($fileSystemRoot, $ProjectRoot)
    if ($env:USERPROFILE) {
        $rejectedRoots += (Get-FullPath -Path $env:USERPROFILE)
    }
    foreach ($rejectedRoot in $rejectedRoots) {
        if ($rejectedRoot -and (Test-PathEqual -Left $fullPath -Right $rejectedRoot)) {
            throw "BackupRoot must be a dedicated directory, not a filesystem, home, or repository root: $fullPath"
        }
    }

    if (-not (Test-Path -LiteralPath $fullPath)) {
        if (-not $Create) {
            throw "BackupRoot does not exist: $fullPath"
        }
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
    }

    $item = Get-Item -LiteralPath $fullPath -Force
    if (-not $item.PSIsContainer) {
        throw "BackupRoot is not a directory: $fullPath"
    }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "BackupRoot must not be a symbolic link or reparse point: $fullPath"
    }
    return $item.FullName
}

function Get-DirectChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $candidate = Get-FullPath -Path (Join-Path $Root $Name)
    $parent = [System.IO.Directory]::GetParent($candidate)
    if ($null -eq $parent -or -not (Test-PathEqual -Left $parent.FullName -Right $Root)) {
        throw "Resolved backup path is not a direct child of BackupRoot."
    }
    return $candidate
}

function Resolve-BackupDirectory {
    Assert-BackupId
    $root = Resolve-SafeBackupRoot
    $directory = Get-DirectChildPath -Root $root -Name $BackupId
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "BackupId was not found under BackupRoot: $BackupId"
    }
    $item = Get-Item -LiteralPath $directory -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Backup directory must not be a symbolic link or reparse point: $directory"
    }
    return $item.FullName
}

function Remove-PartialBackupDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Directory
    )

    $parent = [System.IO.Directory]::GetParent((Get-FullPath -Path $Directory))
    $leaf = Split-Path -Leaf $Directory
    if ($null -eq $parent -or -not (Test-PathEqual -Left $parent.FullName -Right $Root) -or -not $leaf.EndsWith(".partial")) {
        throw "Refusing to clean an unverified partial backup path: $Directory"
    }
    if (Test-Path -LiteralPath $Directory) {
        Remove-Item -LiteralPath $Directory -Recurse -Force
    }
}

function Get-DockerLines {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($exitCode -ne 0) {
        $detail = (@($output) | ForEach-Object { "$_" }) -join [Environment]::NewLine
        throw "Docker command failed (exit $exitCode): docker $($Arguments -join ' ')`n$detail"
    }
    return @($output | ForEach-Object { "$($_)" } | Where-Object { $_.Trim() })
}

function Get-DockerOutput {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    return (Get-DockerLines -Arguments $Arguments) -join [Environment]::NewLine
}

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $lines = Get-DockerLines -Arguments $Arguments
    foreach ($line in $lines) {
        Write-Host $line
    }
}

function Write-BackupRecord {
    param(
        [Parameter(Mandatory = $true)][string]$PostgresContainer,
        [Parameter(Mandatory = $true)][ValidateSet("COMPLETED")][string]$Status,
        [Parameter(Mandatory = $true)][string]$StoragePath,
        [Parameter(Mandatory = $true)][string]$Checksum,
        [Parameter(Mandatory = $true)][long]$SizeBytes
    )

    $postgresUser = Get-DockerOutput -Arguments @(
        "exec", $PostgresContainer, "sh", "-c", 'printf "%s" "$POSTGRES_USER"'
    )
    $postgresDatabase = Get-DockerOutput -Arguments @(
        "exec", $PostgresContainer, "sh", "-c", 'printf "%s" "$POSTGRES_DB"'
    )
    $backupIdLiteral = "'" + $BackupId.Replace("'", "''") + "'"
    $statusLiteral = "'" + $Status.Replace("'", "''") + "'"
    $storagePathLiteral = "'" + $StoragePath.Replace("'", "''") + "'"
    $checksumLiteral = "'" + $Checksum.Replace("'", "''") + "'"
    $sql = @"
INSERT INTO backup_records (
    id, venue_id, status, storage_path, checksum, size_bytes,
    error, requested_by, created_at, completed_at
)
SELECT
    $backupIdLiteral || ':' || id,
    id,
    $statusLiteral,
    $storagePathLiteral,
    $checksumLiteral,
    $SizeBytes,
    NULL,
    'mvp-operations-script',
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
FROM venues
ON CONFLICT (id) DO UPDATE SET
    status = EXCLUDED.status,
    storage_path = EXCLUDED.storage_path,
    checksum = EXCLUDED.checksum,
    size_bytes = EXCLUDED.size_bytes,
    error = NULL,
    requested_by = EXCLUDED.requested_by,
    completed_at = EXCLUDED.completed_at;
"@
    Invoke-Docker -Arguments @(
        "exec", $PostgresContainer,
        "psql", "-v", "ON_ERROR_STOP=1",
        "-U", $postgresUser,
        "-d", $postgresDatabase,
        "-c", $sql
    )
}

function Test-DockerEnvironment {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install or start Docker Desktop."
    }

    $serverVersion = Get-DockerOutput -Arguments @("info", "--format", "{{.ServerVersion}}")
    $composeVersion = Get-DockerOutput -Arguments @("compose", "version", "--short")
    return [pscustomobject]@{
        DockerEngine = $serverVersion
        DockerCompose = $composeVersion
    }
}

function Get-ServiceContainers {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service
    )

    return @(Get-DockerLines -Arguments @(
        "ps", "-a",
        "--filter", "label=com.docker.compose.project=$ComposeProject",
        "--filter", "label=com.docker.compose.service=$Service",
        "--filter", "label=com.docker.compose.container-number",
        "--format", "{{.ID}}"
    ))
}

function Get-ServiceContainer {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service,
        [switch]$AllowMissing
    )

    $containers = @(Get-ServiceContainers -ComposeProject $ComposeProject -Service $Service)
    if ($containers.Count -gt 1) {
        throw "Compose project '$ComposeProject' has multiple containers for service '$Service'."
    }
    if ($containers.Count -eq 0) {
        if ($AllowMissing) {
            return $null
        }
        throw "Compose project '$ComposeProject' has no container for service '$Service'."
    }
    return $containers[0]
}

function Get-ProjectVolume {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Volume,
        [switch]$AllowMissing
    )

    $volumes = @(Get-DockerLines -Arguments @(
        "volume", "ls",
        "--filter", "label=com.docker.compose.project=$ComposeProject",
        "--filter", "label=com.docker.compose.volume=$Volume",
        "--format", "{{.Name}}"
    ))
    if ($volumes.Count -gt 1) {
        throw "Compose project '$ComposeProject' has multiple '$Volume' volumes."
    }
    if ($volumes.Count -eq 0) {
        if ($AllowMissing) {
            return $null
        }
        throw "Compose project '$ComposeProject' has no '$Volume' volume."
    }
    return $volumes[0]
}

function New-ProjectVolume {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Volume
    )

    $existing = Get-ProjectVolume -ComposeProject $ComposeProject -Volume $Volume -AllowMissing
    if ($existing) {
        return $existing
    }
    $volumeName = "${ComposeProject}_${Volume}"
    Invoke-Docker -Arguments @(
        "volume", "create",
        "--label", "com.docker.compose.project=$ComposeProject",
        "--label", "com.docker.compose.volume=$Volume",
        $volumeName
    )
    return Get-ProjectVolume -ComposeProject $ComposeProject -Volume $Volume
}

function Test-DockerVolumeExists {
    param([Parameter(Mandatory = $true)][string]$Volume)

    $volumes = @(Get-DockerLines -Arguments @("volume", "ls", "--format", "{{.Name}}"))
    return $volumes -ccontains $Volume
}

function Assert-VolumeEmpty {
    param(
        [Parameter(Mandatory = $true)][string]$Volume,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $entries = @(Get-DockerLines -Arguments @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=volume,source=$Volume,target=/data,readonly",
        $ArchiveImage,
        "ls", "-A", "/data"
    ))
    if ($entries.Count -gt 0) {
        throw "$Label volume must be empty before restore."
    }
}

function Initialize-EmptySecretsVolume {
    param([Parameter(Mandatory = $true)][string]$Volume)

    if (-not (Test-DockerVolumeExists -Volume $Volume)) {
        Invoke-Docker -Arguments @(
            "volume", "create",
            "--label", "memory-palace.restore.secrets=true",
            "--label", "memory-palace.restore.target=$TargetProject",
            $Volume
        )
    }
    Assert-VolumeEmpty -Volume $Volume -Label "Target secrets"
}

function Initialize-RestoreApplicationSecret {
    param([Parameter(Mandatory = $true)][string]$Volume)

    $placeholder = "sk-restore-disabled-local-only"
    $dockerArguments = @(
        "run", "--rm", "-i", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=volume,source=$Volume,target=/secrets",
        $ArchiveImage,
        "sh", "-eu", "-c",
        'umask 077; cat > /secrets/deepseek_api_key; chmod 0444 /secrets/deepseek_api_key'
    )
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = $placeholder | & docker @dockerArguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
        $placeholder = $null
    }
    if ($exitCode -ne 0) {
        throw "Could not initialize the isolated restore application secret."
    }
    if (@($output | Where-Object { "$($_)".Trim() }).Count -gt 0) {
        Write-Warning "Restore secret helper produced unexpected output."
    }
}

function Get-ProjectResourceCount {
    param([Parameter(Mandatory = $true)][string]$ComposeProject)

    $containers = @(Get-DockerLines -Arguments @(
        "ps", "-a", "--filter", "label=com.docker.compose.project=$ComposeProject", "--format", "{{.ID}}"
    ))
    $volumes = @(Get-DockerLines -Arguments @(
        "volume", "ls", "--filter", "label=com.docker.compose.project=$ComposeProject", "--format", "{{.Name}}"
    ))
    $networks = @(Get-DockerLines -Arguments @(
        "network", "ls", "--filter", "label=com.docker.compose.project=$ComposeProject", "--format", "{{.ID}}"
    ))
    return $containers.Count + $volumes.Count + $networks.Count
}

function Get-ContainerStatusRows {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service
    )

    $containers = @(Get-ServiceContainers -ComposeProject $ComposeProject -Service $Service)
    if ($containers.Count -eq 0) {
        return [pscustomobject]@{
            Service = $Service
            Container = "-"
            State = "missing"
            Health = "missing"
            Image = "-"
        }
    }

    foreach ($container in $containers) {
        [pscustomobject]@{
            Service = $Service
            Container = Get-DockerOutput -Arguments @("inspect", "--format", "{{.Name}}", $container)
            State = Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Status}}", $container)
            Health = Get-DockerOutput -Arguments @(
                "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}", $container
            )
            Image = Get-DockerOutput -Arguments @("inspect", "--format", "{{.Config.Image}}", $container)
        }
    }
}

function Wait-ContainerReady {
    param(
        [Parameter(Mandatory = $true)][string]$Container,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Status}}", $Container)
        $health = Get-DockerOutput -Arguments @(
            "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}", $Container
        )
        if ($state -eq "running" -and $health -eq "healthy") {
            return
        }
        if ($state -eq "running" -and $health -eq "not-configured") {
            throw "Container $Container has no healthcheck; every formal service must define and pass one."
        }
        if ($state -in @("dead", "exited")) {
            throw "Container $Container entered state '$state' while waiting for readiness."
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    throw "Container $Container was not ready within $TimeoutSeconds seconds."
}

function Get-ServiceManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service
    )

    $containers = @(Get-ServiceContainers -ComposeProject $ComposeProject -Service $Service)
    if ($containers.Count -eq 0) {
        return [ordered]@{ present = $false; container_count = 0; containers = @() }
    }
    $containerManifests = @()
    foreach ($container in $containers) {
        $containerManifests += [ordered]@{
            name = Get-DockerOutput -Arguments @("inspect", "--format", "{{.Name}}", $container)
            image = Get-DockerOutput -Arguments @("inspect", "--format", "{{.Config.Image}}", $container)
            image_id = Get-DockerOutput -Arguments @("inspect", "--format", "{{.Image}}", $container)
        }
    }
    return [ordered]@{
        present = $true
        container_count = $containers.Count
        containers = $containerManifests
    }
}

function Get-GitManifest {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        return [ordered]@{ available = $false }
    }

    $revision = (& git -C $ProjectRoot rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return [ordered]@{ available = $false }
    }
    $status = @(& git -C $ProjectRoot status --porcelain 2>$null)
    return [ordered]@{
        available = $true
        revision = "$revision".Trim()
        dirty = $status.Count -gt 0
    }
}

function New-BackupId {
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 8)
    return "mp-$($Project.ToLowerInvariant())-$timestamp-$suffix".ToLowerInvariant()
}

function Invoke-VolumeArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Volume,
        [Parameter(Mandatory = $true)][string]$DestinationDirectory,
        [Parameter(Mandatory = $true)][string]$ArtifactName
    )

    Invoke-Docker -Arguments @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=volume,source=$Volume,target=/source,readonly",
        "--mount", "type=bind,source=$DestinationDirectory,target=/backup",
        $ArchiveImage,
        "tar", "-C", "/source", "-czf", "/backup/$ArtifactName", "."
    )
}

function Test-VolumeArchiveEntries {
    param(
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $entries = @(Get-DockerLines -Arguments @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
        $ArchiveImage,
        "tar", "-tzf", "/backup/$ArtifactName"
    ))
    $verboseEntries = @(Get-DockerLines -Arguments @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
        $ArchiveImage,
        "tar", "-tvzf", "/backup/$ArtifactName"
    ))
    if ($entries.Count -ne $verboseEntries.Count) {
        throw "$Label archive listing is inconsistent."
    }
    for ($index = 0; $index -lt $entries.Count; $index++) {
        $entry = $entries[$index]
        $normalized = $entry.Replace('\', '/')
        $segments = @($normalized.Split('/') | Where-Object { $_ })
        if ($normalized.StartsWith('/') -or $segments -contains "..") {
            throw "$Label archive contains an unsafe path: $entry"
        }
        $entryType = if ($verboseEntries[$index]) { $verboseEntries[$index].Substring(0, 1) } else { "" }
        if ($entryType -notin @("-", "d")) {
            throw "$Label archive contains a non-regular entry."
        }
    }
}

function Expand-VolumeArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Volume,
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [Parameter(Mandatory = $true)][string]$ArtifactName,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Test-VolumeArchiveEntries -BackupDirectory $BackupDirectory -ArtifactName $ArtifactName -Label $Label
    Assert-VolumeEmpty -Volume $Volume -Label $Label
    Invoke-Docker -Arguments @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=volume,source=$Volume,target=/restore",
        "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
        $ArchiveImage,
        "tar", "--no-same-permissions", "-C", "/restore", "-xozf", "/backup/$ArtifactName"
    )
}

function Invoke-Backup {
    Assert-ProjectName -Name $Project -ParameterName "Project"
    $composePath = Resolve-ExistingFile -Path $ComposeFile -ParameterName "ComposeFile"
    $versions = Test-DockerEnvironment
    $root = Resolve-SafeBackupRoot -Create
    $backupDrive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($root))
    if ($backupDrive.AvailableFreeSpace -lt 1GB) {
        throw "Backup destination has less than 1 GiB free space: $($backupDrive.Name)"
    }
    if (-not $BackupId) {
        $script:BackupId = New-BackupId
    }
    Assert-BackupId

    $finalDirectory = Get-DirectChildPath -Root $root -Name $BackupId
    $partialDirectory = Get-DirectChildPath -Root $root -Name "$BackupId.partial"
    if ((Test-Path -LiteralPath $finalDirectory) -or (Test-Path -LiteralPath $partialDirectory)) {
        throw "BackupId already exists: $BackupId"
    }

    $postgresContainer = Get-ServiceContainer -ComposeProject $Project -Service "postgres"
    $chromaContainer = Get-ServiceContainer -ComposeProject $Project -Service "chromadb"
    $appContainers = @(Get-ServiceContainers -ComposeProject $Project -Service "app")
    if ($appContainers.Count -gt 1) {
        throw "Backup requires exactly one App container; project '$Project' has $($appContainers.Count). Run doctor and resolve duplicate writers first."
    }
    $chromaVolume = Get-ProjectVolume -ComposeProject $Project -Volume "chroma-data"
    $embeddingVolume = Get-ProjectVolume -ComposeProject $Project -Volume "embedding-cache"
    $postgresState = Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Status}}", $postgresContainer)
    if ($postgresState -ne "running") {
        throw "PostgreSQL must be running before backup; current state: $postgresState"
    }

    New-Item -ItemType Directory -Path $partialDirectory | Out-Null
    $runningAppContainers = @()
    $chromaWasRunning = $false
    $backupError = $null
    try {
        foreach ($appContainer in $appContainers) {
            if ((Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Running}}", $appContainer)) -eq "true") {
                $runningAppContainers += $appContainer
            }
        }
        $chromaWasRunning = (Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Running}}", $chromaContainer)) -eq "true"

        foreach ($appContainer in $runningAppContainers) {
            Invoke-Docker -Arguments @("stop", $appContainer)
        }
        if ($chromaWasRunning) {
            Invoke-Docker -Arguments @("stop", $chromaContainer)
        }

        $containerDump = "/tmp/memory-palace-$BackupId.dump"
        try {
            Invoke-Docker -Arguments @(
                "exec", $postgresContainer, "sh", "-c",
                'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$1"', "backup", $containerDump
            )
            Invoke-Docker -Arguments @(
                "cp", "${postgresContainer}:$containerDump", (Join-Path $partialDirectory $PostgresArtifactName)
            )
        }
        finally {
            try {
                Get-DockerOutput -Arguments @("exec", $postgresContainer, "rm", "-f", $containerDump) | Out-Null
            }
            catch {
                Write-Warning "Could not remove temporary PostgreSQL dump from container $postgresContainer."
            }
        }

        Invoke-VolumeArchive `
            -Volume $chromaVolume `
            -DestinationDirectory $partialDirectory `
            -ArtifactName $ChromaArtifactName
        Invoke-VolumeArchive `
            -Volume $embeddingVolume `
            -DestinationDirectory $partialDirectory `
            -ArtifactName $EmbeddingArtifactName
    }
    catch {
        $backupError = $_
    }
    finally {
        if ($chromaWasRunning) {
            try {
                Invoke-Docker -Arguments @("start", $chromaContainer)
                Wait-ContainerReady -Container $chromaContainer
            }
            catch {
                if (-not $backupError) {
                    $backupError = $_
                }
                else {
                    Write-Warning "ChromaDB could not be restarted after backup failure: $($_.Exception.Message)"
                }
            }
        }
        foreach ($appContainer in $runningAppContainers) {
            try {
                Invoke-Docker -Arguments @("start", $appContainer)
                Wait-ContainerReady -Container $appContainer -TimeoutSeconds 180
            }
            catch {
                if (-not $backupError) {
                    $backupError = $_
                }
                else {
                    Write-Warning "App could not be restarted after backup failure: $($_.Exception.Message)"
                }
            }
        }
    }
    if ($backupError) {
        Remove-PartialBackupDirectory -Root $root -Directory $partialDirectory
        throw $backupError
    }

    try {
        $postgresArtifact = Join-Path $partialDirectory $PostgresArtifactName
        $chromaArtifact = Join-Path $partialDirectory $ChromaArtifactName
        $embeddingArtifact = Join-Path $partialDirectory $EmbeddingArtifactName
        if (-not (Test-Path -LiteralPath $postgresArtifact -PathType Leaf) -or
            -not (Test-Path -LiteralPath $chromaArtifact -PathType Leaf) -or
            -not (Test-Path -LiteralPath $embeddingArtifact -PathType Leaf)) {
            throw "Backup did not produce all required artifacts."
        }
        Test-VolumeArchiveEntries `
            -BackupDirectory $partialDirectory `
            -ArtifactName $ChromaArtifactName `
            -Label "Chroma"
        Test-VolumeArchiveEntries `
            -BackupDirectory $partialDirectory `
            -ArtifactName $EmbeddingArtifactName `
            -Label "Embedding cache"

        $services = [ordered]@{}
        foreach ($service in @("app", "postgres", "redis", "chromadb", "nginx")) {
            $services[$service] = Get-ServiceManifest -ComposeProject $Project -Service $service
        }

        $manifest = [ordered]@{
            schema_version = $ManifestSchema
            script_version = $ScriptVersion
            backup_id = $BackupId
            created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            source = [ordered]@{
                compose_project = $Project
                compose_file_sha256 = (Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash.ToLowerInvariant()
                git = Get-GitManifest
            }
            versions = [ordered]@{
                docker_engine = $versions.DockerEngine
                docker_compose = $versions.DockerCompose
                archive_image = $ArchiveImage
                postgres = Get-DockerOutput -Arguments @("exec", $postgresContainer, "postgres", "--version")
                services = $services
            }
            source_storage = [ordered]@{
                chroma_volume = $chromaVolume
                embedding_cache_volume = $embeddingVolume
            }
            artifacts = [ordered]@{
                postgres = [ordered]@{
                    file = $PostgresArtifactName
                    bytes = (Get-Item -LiteralPath $postgresArtifact).Length
                    sha256 = (Get-FileHash -LiteralPath $postgresArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
                }
                chroma = [ordered]@{
                    file = $ChromaArtifactName
                    bytes = (Get-Item -LiteralPath $chromaArtifact).Length
                    sha256 = (Get-FileHash -LiteralPath $chromaArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
                }
                embedding_cache = [ordered]@{
                    file = $EmbeddingArtifactName
                    bytes = (Get-Item -LiteralPath $embeddingArtifact).Length
                    sha256 = (Get-FileHash -LiteralPath $embeddingArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
                }
            }
        }
        $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $partialDirectory $ManifestName) -Encoding utf8
        Move-Item -LiteralPath $partialDirectory -Destination $finalDirectory
        $manifestPath = Join-Path $finalDirectory $ManifestName
        $manifestChecksum = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $totalBytes = (Get-ChildItem -LiteralPath $finalDirectory -File | Measure-Object -Property Length -Sum).Sum
        Write-BackupRecord `
            -PostgresContainer $postgresContainer `
            -Status "COMPLETED" `
            -StoragePath $finalDirectory `
            -Checksum $manifestChecksum `
            -SizeBytes $totalBytes
        Write-Host "Backup complete: $BackupId"
        Write-Host "Location: $finalDirectory"
    }
    catch {
        Remove-PartialBackupDirectory -Root $root -Directory $partialDirectory
        throw
    }
}

function Assert-RestoreParameters {
    Assert-ProjectName -Name $Project -ParameterName "Project"
    if (-not $TargetProject) {
        throw "TargetProject is required for restore and must explicitly name the destination Compose project."
    }
    Assert-ProjectName -Name $TargetProject -ParameterName "TargetProject"
    Assert-BackupId
    if ($ConfirmTarget -cne $TargetProject) {
        throw "ConfirmTarget must exactly match destination project '$TargetProject'."
    }
    if ($TargetProject -ceq $Project -and -not $Force) {
        throw "Restoring over the source project requires -Force in addition to exact confirmation."
    }
    if (-not $EnvFile) {
        throw "EnvFile is required for restore; provide a secure file containing the target Compose secrets."
    }
    if (-not $TargetSecretsVolume) {
        throw "TargetSecretsVolume is required for restore and must name an isolated empty Docker volume."
    }
    Assert-DockerVolumeName -Name $TargetSecretsVolume -ParameterName "TargetSecretsVolume"
    $expectedSecretsVolume = "$TargetProject-secrets"
    if ($TargetSecretsVolume -cne $expectedSecretsVolume) {
        throw "TargetSecretsVolume must be the target-dedicated volume '$expectedSecretsVolume'; shared volumes are forbidden."
    }
}

function Read-VerifiedManifest {
    param([Parameter(Mandatory = $true)][string]$BackupDirectory)

    $manifestPath = Resolve-ExistingFile -Path (Join-Path $BackupDirectory $ManifestName) -ParameterName "Manifest"
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
    }
    catch {
        throw "Manifest is not valid JSON: $manifestPath"
    }

    if ($manifest.schema_version -cne $ManifestSchema) {
        throw "Unsupported manifest schema: $($manifest.schema_version)"
    }
    if ($manifest.backup_id -cne $BackupId) {
        throw "Manifest backup_id does not match requested BackupId."
    }
    if ("$($manifest.source.compose_file_sha256)" -notmatch '^[a-fA-F0-9]{64}$') {
        throw "Manifest contains an invalid Compose file checksum."
    }
    if ($manifest.artifacts.postgres.file -cne $PostgresArtifactName -or
        $manifest.artifacts.chroma.file -cne $ChromaArtifactName -or
        $manifest.artifacts.embedding_cache.file -cne $EmbeddingArtifactName) {
        throw "Manifest contains unexpected artifact names."
    }

    foreach ($artifact in @(
        @{ Name = "PostgreSQL"; File = $PostgresArtifactName; Metadata = $manifest.artifacts.postgres },
        @{ Name = "Chroma"; File = $ChromaArtifactName; Metadata = $manifest.artifacts.chroma },
        @{ Name = "Embedding cache"; File = $EmbeddingArtifactName; Metadata = $manifest.artifacts.embedding_cache }
    )) {
        if ("$($artifact.Metadata.sha256)" -notmatch '^[a-fA-F0-9]{64}$') {
            throw "$($artifact.Name) artifact contains an invalid checksum."
        }
        $artifactPath = Resolve-ExistingFile -Path (Join-Path $BackupDirectory $artifact.File) -ParameterName "$($artifact.Name) artifact"
        $actual = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne "$($artifact.Metadata.sha256)".ToLowerInvariant()) {
            throw "$($artifact.Name) artifact checksum mismatch."
        }
        $expectedBytes = [long]0
        if ($null -eq $artifact.Metadata.bytes -or
            -not [long]::TryParse("$($artifact.Metadata.bytes)", [ref]$expectedBytes) -or
            $expectedBytes -lt 0 -or
            (Get-Item -LiteralPath $artifactPath).Length -ne $expectedBytes) {
            throw "$($artifact.Name) artifact size does not match the manifest."
        }
    }
    return $manifest
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)][string]$ResolvedComposeFile,
        [Parameter(Mandatory = $true)][string]$ResolvedEnvFile,
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $composeArguments = @(
        "compose", "--env-file", $ResolvedEnvFile, "-f", $ResolvedComposeFile, "-p", $ComposeProject
    ) + $Arguments
    Invoke-Docker -Arguments $composeArguments
}

function Invoke-Install {
    $context = Get-DeploymentContext
    $release = Get-ReleaseRevision

    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        if (-not (Test-DockerVolumeExists -Volume $context.SecretsVolume)) {
            Invoke-Docker -Arguments @(
                "volume", "create",
                "--label", "memory-palace.secrets=true",
                "--label", "memory-palace.project=$($context.Project)",
                $context.SecretsVolume
            )
        }
        if ($Offline) {
            Write-Host "Offline install: using locally cached pinned images."
        }
        else {
            Invoke-Docker -Arguments @("pull", $ArchiveImage)
            Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
                -ComposeProject $context.Project -Arguments @("pull", "postgres", "redis", "chromadb", "nginx")
        }
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("build", "app")
        Register-ReleaseImage -Context $context -Release $release
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }

    Write-Host "Install complete for project $($context.Project) (Docker $($context.DockerEngine), Compose $($context.DockerCompose))."
    Write-Host "No credential was written. Inject DeepSeek into external volume '$($context.SecretsVolume)' before start."
}

function Get-DeploymentContext {
    Assert-DeploymentParameters
    Assert-DockerVolumeName -Name $SecretsVolume -ParameterName "SecretsVolume"
    $versions = Test-DockerEnvironment
    return [pscustomobject]@{
        ComposeFile = Resolve-ExistingFile -Path $ComposeFile -ParameterName "ComposeFile"
        EnvFile = Resolve-ExistingFile -Path $EnvFile -ParameterName "EnvFile"
        Project = $Project
        SecretsVolume = $SecretsVolume
        DockerEngine = $versions.DockerEngine
        DockerCompose = $versions.DockerCompose
    }
}

function Get-ReleaseRevision {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw "Git is required to pin the formal application build to a release revision."
    }

    $revision = (& git -C $ProjectRoot rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not "$revision".Trim()) {
        throw "Could not resolve the Git HEAD used for the formal application build."
    }
    $revision = "$revision".Trim().ToLowerInvariant()
    if ($revision -notmatch '^[a-f0-9]{40,64}$') {
        throw "Git HEAD is not a valid immutable revision."
    }

    $status = @(& git -C $ProjectRoot status --porcelain --untracked-files=all 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify whether the application worktree is clean."
    }
    $dirty = $status.Count -gt 0
    if ($dirty -and -not $AllowDirtyBuild) {
        throw "Formal install and upgrade require a clean Git worktree. Commit the approved release or use -AllowDirtyBuild only for internal development."
    }
    if ($dirty) {
        Write-Warning "Building an internal dirty-worktree image at HEAD $revision; customer releases must not use -AllowDirtyBuild."
    }
    return [pscustomobject]@{
        Revision = $revision
        Dirty = $dirty
        Tag = $revision.Substring(0, 12) + $(if ($dirty) { "-dirty" } else { "" })
    }
}

function Register-ReleaseImage {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Context,
        [Parameter(Mandatory = $true)][pscustomobject]$Release
    )

    $appImage = "$($Context.Project)-app:latest"
    $imageId = Get-DockerOutput -Arguments @(
        "image", "inspect", "--format", "{{.Id}}", $appImage
    )
    if (-not $imageId -or $imageId.Contains([Environment]::NewLine)) {
        throw "Docker did not return exactly one App image after build."
    }
    $releaseImage = "$($Context.Project)-app:$($Release.Tag)"
    Invoke-Docker -Arguments @("image", "tag", $imageId, $releaseImage)
    Write-Host "Release revision: $($Release.Revision)"
    Write-Host "Release image: $releaseImage ($imageId)"
}

function Test-DeploymentSecretAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Volume,
        [ValidatePattern('^[a-z0-9][a-z0-9_.-]{1,127}$')]
        [string]$SecretName = "deepseek_api_key"
    )

    $dockerArguments = @(
        "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--mount", "type=volume,source=$Volume,target=/secrets,readonly",
        $ArchiveImage,
        "test", "-s", "/secrets/$SecretName"
    )
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker volume inspect $Volume 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        & docker @dockerArguments 1>$null 2>$null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    return $exitCode -eq 0
}

function Wait-ServiceReady {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service,
        [int]$TimeoutSeconds = 180
    )

    $container = Get-ServiceContainer -ComposeProject $ComposeProject -Service $Service
    Wait-ContainerReady -Container $container -TimeoutSeconds $TimeoutSeconds
}

function Get-ServiceRuntimeIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeProject,
        [Parameter(Mandatory = $true)][string]$Service
    )

    $container = Get-ServiceContainer -ComposeProject $ComposeProject -Service $Service
    return [pscustomobject]@{
        Container = $container
        ProcessId = Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.Pid}}", $container)
        StartedAt = Get-DockerOutput -Arguments @("inspect", "--format", "{{.State.StartedAt}}", $container)
    }
}

function Invoke-PostgresMigration {
    param([Parameter(Mandatory = $true)][pscustomobject]$Context)

    $migrationCode = @"
import asyncio
import time

from src.memory_palace.api.v1.endpoints.auth import bootstrap_identity_store
from src.memory_palace.knowledge.db_init import init_database
from src.memory_palace.knowledge.postgres_client import PostgresDBClient

MIGRATION_VERSION = "mvp-operations/$ScriptVersion"

async def main():
    client = PostgresDBClient()
    try:
        await init_database(client)
        await bootstrap_identity_store(client)
        await client.execute(
            """CREATE TABLE IF NOT EXISTS mvp_schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at DOUBLE PRECISION NOT NULL
            )"""
        )
        await client.execute(
            """INSERT INTO mvp_schema_migrations (version, applied_at)
            VALUES (?, ?)
            ON CONFLICT(version) DO UPDATE SET applied_at = EXCLUDED.applied_at""",
            (MIGRATION_VERSION, time.time()),
        )
    finally:
        await client.close()

asyncio.run(main())
"@
    $encodedMigration = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($migrationCode))
    $pythonLauncher = "import base64; exec(base64.b64decode('$encodedMigration'))"
    Invoke-Compose -ResolvedComposeFile $Context.ComposeFile -ResolvedEnvFile $Context.EnvFile `
        -ComposeProject $Context.Project `
        -Arguments @("run", "--rm", "--no-deps", "app", "python", "-c", $pythonLauncher)
    Write-Host "PostgreSQL migration complete: mvp-operations/$ScriptVersion"
}

function Invoke-Start {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        if (-not (Test-DeploymentSecretAvailable -Volume $context.SecretsVolume)) {
            throw "DeepSeek secret is missing from external volume '$($context.SecretsVolume)'. Run scripts\set_deepseek_secret.ps1, then retry start."
        }

        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "postgres", "redis", "chromadb")
        foreach ($service in @("postgres", "redis", "chromadb")) {
            Wait-ServiceReady -ComposeProject $context.Project -Service $service
        }

        Invoke-PostgresMigration -Context $context

        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "--no-deps", "app")
        Wait-ServiceReady -ComposeProject $context.Project -Service "app"
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "--no-deps", "nginx")
        Wait-ServiceReady -ComposeProject $context.Project -Service "nginx"
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
    Write-Host "Start complete: project $($context.Project) is healthy."
}

function Invoke-Migrate {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "postgres")
        Wait-ServiceReady -ComposeProject $context.Project -Service "postgres"
        Invoke-PostgresMigration -Context $context
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
}

function Invoke-UatBootstrap {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        if (-not (Test-DeploymentSecretAvailable -Volume $context.SecretsVolume -SecretName "uat_employee_password")) {
            throw "UAT employee credential is missing from external volume '$($context.SecretsVolume)'. Run scripts\set_uat_employee_secret.ps1, then retry bootstrap-uat."
        }
        Wait-ServiceReady -ComposeProject $context.Project -Service "app"
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project `
            -Arguments @("exec", "-T", "app", "python", "scripts/bootstrap_uat.py")
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
}

function Invoke-Verify {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        if (-not (Test-DeploymentSecretAvailable -Volume $context.SecretsVolume)) {
            throw "DeepSeek secret is missing from external volume '$($context.SecretsVolume)'."
        }
        Invoke-Doctor

        $appContainer = Get-ServiceContainer -ComposeProject $context.Project -Service "app"
        $nginxContainer = Get-ServiceContainer -ComposeProject $context.Project -Service "nginx"
        Get-DockerOutput -Arguments @(
            "exec", $appContainer, "curl", "-fsS", "http://localhost:8000/health"
        ) | Out-Null
        Get-DockerOutput -Arguments @(
            "exec", $nginxContainer, "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/health"
        ) | Out-Null
        Get-DockerOutput -Arguments @(
            "exec", $nginxContainer, "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/admin/"
        ) | Out-Null
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
    Write-Host "Verification result: PASS (runtime health and formal client reachable)."
}

function Protect-LogText {
    param([AllowEmptyString()][string]$Line)

    $protected = $Line -replace '(?i)(authorization\s*:\s*bearer\s+)\S+', '$1[REDACTED]'
    $protected = $protected -replace '(?i)("(?:api[_-]?key|password|token|secret)"\s*:\s*)"[^"]*"', '$1"[REDACTED]"'
    $protected = $protected -replace '(?i)((?:api[_-]?key|password|token|secret)\s*[=:]\s*)\S+', '$1[REDACTED]'
    $protected = $protected -replace '(?i)\bsk-[A-Za-z0-9_-]{8,}\b', '[REDACTED]'
    return $protected
}

function Invoke-RedactedDockerStream {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @Arguments 2>&1 | ForEach-Object {
            Write-Host (Protect-LogText -Line "$_")
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($exitCode -ne 0) {
        throw "Docker logs command failed with exit code $exitCode. Review Docker Desktop and project status."
    }
}

function Invoke-Logs {
    $context = Get-DeploymentContext
    $arguments = @(
        "compose", "--env-file", $context.EnvFile, "-f", $context.ComposeFile,
        "-p", $context.Project, "logs", "--no-color", "--tail", "$Tail"
    )
    if ($Follow) {
        $arguments += "--follow"
    }
    if ($Service) {
        $arguments += $Service
    }

    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        Invoke-RedactedDockerStream -Arguments $arguments
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
}

function Invoke-RestartApp {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        $beforeApp = Get-ServiceRuntimeIdentity -ComposeProject $context.Project -Service "app"
        $dependencyBefore = @{}
        foreach ($service in @("postgres", "redis", "chromadb", "nginx")) {
            $dependencyBefore[$service] = Get-ServiceRuntimeIdentity `
                -ComposeProject $context.Project -Service $service
        }

        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("restart", "app")
        Wait-ServiceReady -ComposeProject $context.Project -Service "app"

        $afterApp = Get-ServiceRuntimeIdentity -ComposeProject $context.Project -Service "app"
        if ($beforeApp.ProcessId -eq $afterApp.ProcessId -and $beforeApp.StartedAt -eq $afterApp.StartedAt) {
            throw "App runtime identity did not change after restart-app."
        }
        foreach ($service in @("postgres", "redis", "chromadb", "nginx")) {
            $before = $dependencyBefore[$service]
            $after = Get-ServiceRuntimeIdentity -ComposeProject $context.Project -Service $service
            if ($before.Container -ne $after.Container -or
                $before.ProcessId -ne $after.ProcessId -or
                $before.StartedAt -ne $after.StartedAt) {
                throw "Non-App service changed during restart-app: $service"
            }
        }

        Write-Host "App runtime before: container=$($beforeApp.Container) pid=$($beforeApp.ProcessId) started=$($beforeApp.StartedAt)"
        Write-Host "App runtime after:  container=$($afterApp.Container) pid=$($afterApp.ProcessId) started=$($afterApp.StartedAt)"
        Write-Host "restart-app result: PASS; PostgreSQL, Redis, ChromaDB, Nginx, and data volumes were not restarted or cleared."
        Write-Host "Diagnostics: open /admin/diagnostics through the deployment HTTP endpoint."
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
}

function Invoke-Stop {
    $context = Get-DeploymentContext
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    try {
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("stop")
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
    Write-Host "Project $($context.Project) stopped. Data volumes and external secrets were preserved."
}

function Write-UpgradeRollbackHint {
    param(
        [Parameter(Mandatory = $true)][string]$CompletedBackupId,
        [Parameter(Mandatory = $true)][pscustomobject]$Context
    )

    $suffix = "-rollback"
    $baseLength = [Math]::Min($Context.Project.Length, 63 - $suffix.Length)
    $recoveryProject = $Context.Project.Substring(0, $baseLength).TrimEnd("-", "_") + $suffix
    $recoverySecretsVolume = "$recoveryProject-secrets"
    $resolvedBackupRoot = Get-FullPath -Path $BackupRoot

    Write-Warning "Upgrade failed after backup '$CompletedBackupId'. Existing data and secrets were not deleted."
    Write-Host "Restore the backup into an isolated recovery project before any cutover:"
    Write-Host "  scripts\mvp.cmd restore -BackupId $CompletedBackupId -BackupRoot `"$resolvedBackupRoot`" -TargetProject $recoveryProject -ConfirmTarget $recoveryProject -EnvFile `"$($Context.EnvFile)`" -TargetSecretsVolume $recoverySecretsVolume -TargetHttpPort 18081"
    Write-Host "After validation, redeploy the previous release and follow the documented cutover procedure."
}

function Invoke-Upgrade {
    $context = Get-DeploymentContext
    $release = Get-ReleaseRevision
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $env:MEMORY_PALACE_SECRETS_VOLUME = $context.SecretsVolume
    $completedBackupId = $null
    try {
        if (-not (Test-DeploymentSecretAvailable -Volume $context.SecretsVolume)) {
            throw "DeepSeek secret is missing from external volume '$($context.SecretsVolume)'. Upgrade did not begin."
        }

        Invoke-Backup
        $completedBackupId = $BackupId

        if ($Offline) {
            Write-Host "Offline upgrade: using locally cached pinned images."
        }
        else {
            Invoke-Docker -Arguments @("pull", $ArchiveImage)
            Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
                -ComposeProject $context.Project -Arguments @("pull", "postgres", "redis", "chromadb", "nginx")
        }
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("build", "app")
        Register-ReleaseImage -Context $context -Release $release

        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "postgres", "redis", "chromadb")
        foreach ($service in @("postgres", "redis", "chromadb")) {
            Wait-ServiceReady -ComposeProject $context.Project -Service $service
        }
        Invoke-PostgresMigration -Context $context

        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "--no-deps", "--force-recreate", "app")
        Wait-ServiceReady -ComposeProject $context.Project -Service "app"
        Invoke-Compose -ResolvedComposeFile $context.ComposeFile -ResolvedEnvFile $context.EnvFile `
            -ComposeProject $context.Project -Arguments @("up", "-d", "--no-deps", "--force-recreate", "nginx")
        Wait-ServiceReady -ComposeProject $context.Project -Service "nginx"

        Invoke-Verify
        Write-Host "Upgrade complete: project $($context.Project), backup $completedBackupId."
    }
    catch {
        if ($completedBackupId) {
            Write-UpgradeRollbackHint -CompletedBackupId $completedBackupId -Context $context
        }
        else {
            Write-Warning "Upgrade stopped before a complete backup was created; images and data were not changed by the upgrade phase."
        }
        throw
    }
    finally {
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
    }
}

function Invoke-Restore {
    Assert-RestoreParameters
    $backupDirectory = Resolve-BackupDirectory
    $resolvedEnvFile = Resolve-ExistingFile -Path $EnvFile -ParameterName "EnvFile"
    $resolvedComposeFile = Resolve-ExistingFile -Path $ComposeFile -ParameterName "ComposeFile"
    $manifest = Read-VerifiedManifest -BackupDirectory $backupDirectory
    if ($TargetProject -ceq $manifest.source.compose_project -and -not $Force) {
        throw "Restoring over the manifest source project requires -Force in addition to exact confirmation."
    }
    $composeHash = (Get-FileHash -LiteralPath $resolvedComposeFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($composeHash -cne "$($manifest.source.compose_file_sha256)".ToLowerInvariant()) {
        if (-not $Force) {
            throw "ComposeFile differs from the backup manifest; review compatibility and rerun with -Force to acknowledge it."
        }
        Write-Warning "ComposeFile checksum differs from the backup manifest; compatibility was explicitly forced."
    }
    $versions = Test-DockerEnvironment
    $resourceCount = Get-ProjectResourceCount -ComposeProject $TargetProject
    if ($resourceCount -gt 0 -and -not $Force) {
        throw "Target Compose project '$TargetProject' already has resources; rerun with exact confirmation and -Force to replace them."
    }

    Write-Host "Restore source: $($manifest.backup_id) from project $($manifest.source.compose_project)"
    Write-Host "Restore target: $TargetProject"
    Write-Host "Docker Engine $($versions.DockerEngine), Compose $($versions.DockerCompose)"

    $previousHttpPort = $env:HTTP_PORT
    $previousSecretsVolume = $env:MEMORY_PALACE_SECRETS_VOLUME
    $previousDeepSeekBaseUrl = $env:DEEPSEEK_BASE_URL
    $env:HTTP_PORT = "$TargetHttpPort"
    $env:MEMORY_PALACE_SECRETS_VOLUME = $TargetSecretsVolume
    try {
        Initialize-EmptySecretsVolume -Volume $TargetSecretsVolume
        if ($resourceCount -gt 0) {
            Write-Warning "Removing containers, networks, and named volumes belonging to confirmed target project '$TargetProject'."
            Invoke-Compose -ResolvedComposeFile $resolvedComposeFile -ResolvedEnvFile $resolvedEnvFile `
                -ComposeProject $TargetProject -Arguments @("down", "--volumes", "--remove-orphans")
        }

        Invoke-Compose -ResolvedComposeFile $resolvedComposeFile -ResolvedEnvFile $resolvedEnvFile `
            -ComposeProject $TargetProject -Arguments @("create", "postgres", "redis", "chromadb")

        $postgresContainer = Get-ServiceContainer -ComposeProject $TargetProject -Service "postgres"
        $chromaContainer = Get-ServiceContainer -ComposeProject $TargetProject -Service "chromadb"
        $chromaVolume = Get-ProjectVolume -ComposeProject $TargetProject -Volume "chroma-data"
        $embeddingVolume = New-ProjectVolume -ComposeProject $TargetProject -Volume "embedding-cache"

        Invoke-Docker -Arguments @("start", $postgresContainer)
        Wait-ContainerReady -Container $postgresContainer
        $containerDump = "/tmp/memory-palace-restore.dump"
        try {
            Invoke-Docker -Arguments @(
                "cp", (Join-Path $backupDirectory $PostgresArtifactName), "${postgresContainer}:$containerDump"
            )
            Invoke-Docker -Arguments @(
                "exec", $postgresContainer, "sh", "-c",
                'pg_restore --clean --if-exists --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$1"',
                "restore", $containerDump
            )
        }
        finally {
            try {
                Get-DockerOutput -Arguments @("exec", $postgresContainer, "rm", "-f", $containerDump) | Out-Null
            }
            catch {
                Write-Warning "Could not remove temporary restore dump from container $postgresContainer."
            }
        }

        Expand-VolumeArchive `
            -Volume $chromaVolume `
            -BackupDirectory $backupDirectory `
            -ArtifactName $ChromaArtifactName `
            -Label "Chroma"
        Expand-VolumeArchive `
            -Volume $embeddingVolume `
            -BackupDirectory $backupDirectory `
            -ArtifactName $EmbeddingArtifactName `
            -Label "Embedding cache"
        Invoke-Compose -ResolvedComposeFile $resolvedComposeFile -ResolvedEnvFile $resolvedEnvFile `
            -ComposeProject $TargetProject -Arguments @("up", "-d", "postgres", "redis", "chromadb")
        Wait-ContainerReady -Container $postgresContainer
        Wait-ContainerReady -Container $chromaContainer

        if ($StartApplication) {
            Initialize-RestoreApplicationSecret -Volume $TargetSecretsVolume
            $env:DEEPSEEK_BASE_URL = "http://127.0.0.1:9/v1"
            Invoke-Compose -ResolvedComposeFile $resolvedComposeFile -ResolvedEnvFile $resolvedEnvFile `
                -ComposeProject $TargetProject -Arguments @("up", "-d")
            foreach ($service in @("app", "nginx")) {
                $container = Get-ServiceContainer -ComposeProject $TargetProject -Service $service
                Wait-ContainerReady -Container $container -TimeoutSeconds 180
            }
            Write-Host "Full restored stack is running on HTTP port $TargetHttpPort."
        }
        else {
            Write-Host "Restored data services are running. App and Nginx remain stopped to prevent unintended external actions."
            Write-Host "After validating target credentials, rerun restore with -StartApplication or start the confirmed target explicitly."
        }
        Write-Host "Restore complete: $BackupId -> $TargetProject"
    }
    finally {
        if ($null -eq $previousHttpPort) {
            Remove-Item Env:HTTP_PORT -ErrorAction SilentlyContinue
        }
        else {
            $env:HTTP_PORT = $previousHttpPort
        }
        if ($null -eq $previousSecretsVolume) {
            Remove-Item Env:MEMORY_PALACE_SECRETS_VOLUME -ErrorAction SilentlyContinue
        }
        else {
            $env:MEMORY_PALACE_SECRETS_VOLUME = $previousSecretsVolume
        }
        if ($null -eq $previousDeepSeekBaseUrl) {
            Remove-Item Env:DEEPSEEK_BASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:DEEPSEEK_BASE_URL = $previousDeepSeekBaseUrl
        }
    }
}

function Write-ProjectStatus {
    param([Parameter(Mandatory = $true)][string]$ComposeProject)

    Assert-ProjectName -Name $ComposeProject -ParameterName "Project"
    $versions = Test-DockerEnvironment
    $rows = @()
    foreach ($service in @("app", "postgres", "redis", "chromadb", "nginx")) {
        $rows += @(Get-ContainerStatusRows -ComposeProject $ComposeProject -Service $service)
    }

    Write-Host "Project: $ComposeProject"
    Write-Host "Docker Engine: $($versions.DockerEngine) | Compose: $($versions.DockerCompose)"
    $rows | Format-Table -AutoSize
}

function Invoke-Doctor {
    Assert-ProjectName -Name $Project -ParameterName "Project"
    $checks = @()
    try {
        $versions = Test-DockerEnvironment
        $checks += [pscustomobject]@{ Check = "Docker Engine"; Status = "PASS"; Detail = $versions.DockerEngine }
        $checks += [pscustomobject]@{ Check = "Docker Compose"; Status = "PASS"; Detail = $versions.DockerCompose }
    }
    catch {
        $checks += [pscustomobject]@{ Check = "Docker runtime"; Status = "FAIL"; Detail = $_.Exception.Message }
        $checks | Format-Table -Wrap -AutoSize
        throw "Doctor found 1 blocking failure."
    }

    foreach ($service in @("app", "postgres", "redis", "chromadb", "nginx")) {
        $statuses = @(Get-ContainerStatusRows -ComposeProject $Project -Service $service)
        if ($statuses.Count -ne 1) {
            $checks += [pscustomobject]@{
                Check = "service:$service"
                Status = "FAIL"
                Detail = "expected exactly one container, found $($statuses.Count)"
            }
            continue
        }
        $status = $statuses[0]
        $healthy = $status.State -eq "running" -and $status.Health -eq "healthy"
        $checks += [pscustomobject]@{
            Check = "service:$service"
            Status = if ($healthy) { "PASS" } else { "FAIL" }
            Detail = "$($status.State) / $($status.Health) / $($status.Image)"
        }
    }

    foreach ($volume in @("pg-data", "chroma-data", "embedding-cache")) {
        $name = Get-ProjectVolume -ComposeProject $Project -Volume $volume -AllowMissing
        $checks += [pscustomobject]@{
            Check = "volume:$volume"
            Status = if ($name) { "PASS" } else { "FAIL" }
            Detail = if ($name) { $name } else { "missing" }
        }
    }

    $dependencyChecks = @(
        @{ Service = "postgres"; Command = @("sh", "-c", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"') },
        @{ Service = "redis"; Command = @("redis-cli", "ping") },
        @{ Service = "chromadb"; Command = @("curl", "-fsS", "http://localhost:8000/api/v1/heartbeat") }
    )
    foreach ($dependency in $dependencyChecks) {
        $containers = @(Get-ServiceContainers -ComposeProject $Project -Service $dependency.Service)
        if ($containers.Count -ne 1) {
            continue
        }
        $container = $containers[0]
        try {
            $detail = Get-DockerOutput -Arguments (@("exec", $container) + $dependency.Command)
            $checks += [pscustomobject]@{ Check = "probe:$($dependency.Service)"; Status = "PASS"; Detail = $detail }
        }
        catch {
            $checks += [pscustomobject]@{
                Check = "probe:$($dependency.Service)"; Status = "FAIL"; Detail = $_.Exception.Message
            }
        }
    }

    try {
        $root = Get-FullPath -Path $BackupRoot
        $drive = [System.IO.DriveInfo]::new([System.IO.Path]::GetPathRoot($root))
        $freeGiB = [Math]::Round($drive.AvailableFreeSpace / 1GB, 2)
        $checks += [pscustomobject]@{
            Check = "backup storage"
            Status = if ($freeGiB -ge 1) { "PASS" } else { "FAIL" }
            Detail = "$freeGiB GiB free at $($drive.Name)"
        }
    }
    catch {
        $checks += [pscustomobject]@{ Check = "backup storage"; Status = "FAIL"; Detail = $_.Exception.Message }
    }

    $checks | Format-Table -Wrap -AutoSize
    $failures = @($checks | Where-Object { $_.Status -eq "FAIL" })
    if ($failures.Count -gt 0) {
        throw "Doctor found $($failures.Count) blocking failure(s)."
    }
    Write-Host "Doctor result: PASS"
}

try {
    switch ($Command) {
        "help" {
            Show-Usage
        }
        "backup" {
            Invoke-Backup
        }
        "restore" {
            Invoke-Restore
        }
        "status" {
            Write-ProjectStatus -ComposeProject $Project
        }
        "doctor" {
            Invoke-Doctor
        }
        "install" {
            Invoke-Install
        }
        "start" {
            Invoke-Start
        }
        "migrate" {
            Invoke-Migrate
        }
        "bootstrap-uat" {
            Invoke-UatBootstrap
        }
        "verify" {
            Invoke-Verify
        }
        "logs" {
            Invoke-Logs
        }
        "restart-app" {
            Invoke-RestartApp
        }
        "stop" {
            Invoke-Stop
        }
        "upgrade" {
            Invoke-Upgrade
        }
    }
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
