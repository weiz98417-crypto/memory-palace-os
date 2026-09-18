$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$ScriptPath = Join-Path $ProjectRoot "scripts\mvp.ps1"
$SystemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$TestRoot = Join-Path $SystemTemp "memory-palace-mvp-tests-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $TestRoot | Out-Null

function Assert-Rejected {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string[]]$ExpectedText
    )

    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    $text = (@($output) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($exitCode -eq 0) {
        throw "$Name expected a non-zero exit code."
    }
    foreach ($expected in $ExpectedText) {
        if ($text -notmatch [regex]::Escape($expected)) {
            throw "$Name did not include expected text '$expected'. Output: $text"
        }
    }
    Write-Host "$Name`: PASS"
}

try {
    $helpOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath help 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "help command returned a non-zero exit code."
    }
    $helpText = (@($helpOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    foreach ($command in @(
        "install", "start", "status", "migrate", "bootstrap-uat", "verify", "backup",
        "restore", "logs", "upgrade", "stop", "doctor"
    )) {
        if ($helpText -notmatch [regex]::Escape("mvp.cmd $command")) {
            throw "help command is missing '$command'. Output: $helpText"
        }
    }
    Write-Host "complete command help: PASS"

    foreach ($command in @("install", "start", "migrate", "bootstrap-uat", "verify", "logs", "upgrade", "stop")) {
        Assert-Rejected -Name "$command requires explicit environment" -Arguments @(
            $command
        ) -ExpectedText @("EnvFile")
    }

    $fakeBin = Join-Path $TestRoot "fake-bin"
    $fakeDockerLog = Join-Path $TestRoot "docker.log"
    $fakeEnvFile = Join-Path $TestRoot "deployment.env"
    New-Item -ItemType Directory -Path $fakeBin | Out-Null
    @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$DockerArguments)

$global:LASTEXITCODE = 0
$joined = $DockerArguments -join " "
Add-Content -LiteralPath $env:MVP_FAKE_DOCKER_LOG -Value $joined

if ($DockerArguments[0] -eq "info") {
    Write-Output "27.3.1"
    return
}
if ($DockerArguments[0] -eq "compose" -and $DockerArguments[1] -eq "version") {
    Write-Output "2.29.7"
    return
}
if ($DockerArguments[0] -eq "image" -and $DockerArguments[1] -eq "inspect") {
    Write-Output "sha256:fake-app-image"
    return
}
if ($env:MVP_FAKE_UPGRADE_FAIL -and $DockerArguments[0] -eq "compose" -and $joined.Contains(" build app")) {
    Write-Output "simulated image build failure"
    $global:LASTEXITCODE = 42
    return
}
if ($DockerArguments[0] -eq "compose" -and $joined.Contains(" logs ")) {
    Write-Output "password=admin-sentinel-must-not-be-read"
    Write-Output "Authorization: Bearer token-sentinel-must-not-be-read"
    Write-Output "provider_key=sk-secret-sentinel-must-not-be-read"
    return
}
if ($DockerArguments[0] -eq "volume" -and $DockerArguments[1] -eq "ls") {
    if ($env:MVP_FAKE_RUNTIME_READY) {
        if ($joined.Contains("volume=pg-data")) { Write-Output "memory-palace-test_pg-data" }
    }
    return
}
if ($DockerArguments[0] -eq "ps") {
    foreach ($service in @("postgres", "redis", "app", "nginx")) {
        if ($joined.Contains("service=$service")) {
            Write-Output "$service-test"
            return
        }
    }
    return
}
if ($DockerArguments[0] -eq "exec" -and $joined.Contains("POSTGRES_USER") -and $joined.Contains("printf")) {
    Write-Output "mp_user"
    return
}
if ($DockerArguments[0] -eq "exec" -and $joined.Contains("POSTGRES_DB") -and $joined.Contains("printf")) {
    Write-Output "memory_palace"
    return
}
if ($DockerArguments[0] -eq "inspect") {
    if ($DockerArguments[2] -eq "{{.State.Status}}") { Write-Output "running" }
    elseif ($env:MVP_FAKE_NO_HEALTHCHECK) { Write-Output "not-configured" }
    else { Write-Output "healthy" }
    return
}
if ($DockerArguments[0] -eq "cp" -and $DockerArguments.Count -ge 3 -and
    $DockerArguments[1] -match '^[^:]+:/') {
    [System.IO.File]::WriteAllBytes($DockerArguments[2], [byte[]](1, 2, 3, 4))
    return
}
if ($DockerArguments[0] -eq "run" -and $joined.Contains(" -czf /backup/")) {
    $backupMount = $DockerArguments | Where-Object { $_ -like "type=bind,source=*,target=/backup" } | Select-Object -First 1
    $artifactArgument = $DockerArguments | Where-Object { $_ -like "/backup/*" } | Select-Object -Last 1
    if ($backupMount -match '^type=bind,source=(.+),target=/backup$' -and $artifactArgument) {
        $artifactPath = Join-Path $Matches[1] (Split-Path -Leaf $artifactArgument)
        [System.IO.File]::WriteAllBytes($artifactPath, [byte[]](5, 6, 7, 8))
    }
    return
}
'@ | Set-Content -LiteralPath (Join-Path $fakeBin "docker.ps1") -Encoding utf8
    @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArguments)

if ($env:MVP_FAKE_GIT_DIRTY) {
    if ($GitArguments -contains "rev-parse") {
        Write-Output ("a" * 40)
        $global:LASTEXITCODE = 0
        return
    }
    if ($GitArguments -contains "status") {
        Write-Output " M internal-development-change"
        $global:LASTEXITCODE = 0
        return
    }
}
& git.exe @GitArguments
$global:LASTEXITCODE = $LASTEXITCODE
'@ | Set-Content -LiteralPath (Join-Path $fakeBin "git.ps1") -Encoding utf8
    @'
POSTGRES_PASSWORD=database-sentinel-must-not-be-read
ADMIN_PASSWORD=admin-sentinel-must-not-be-read
MEMORY_PALACE_JWT_SECRET=jwt-sentinel-must-not-be-read
'@ | Set-Content -LiteralPath $fakeEnvFile -Encoding utf8

    $customComposeFile = Join-Path $TestRoot "custom-compose.yml"
    Set-Content -LiteralPath $customComposeFile -Value "services: {}" -Encoding utf8
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        Assert-Rejected -Name "formal compose cannot be overridden" -Arguments @(
            "install", "-Project", "memory-palace-test", "-EnvFile", $fakeEnvFile,
            "-SecretsVolume", "memory-palace-test-secrets", "-ComposeFile", $customComposeFile,
            "-AllowDirtyBuild"
        ) -ExpectedText @("official ComposeFile", "deploy\docker-compose.yml")

        $previousFakeGitDirty = $env:MVP_FAKE_GIT_DIRTY
        $env:MVP_FAKE_GIT_DIRTY = "1"
        try {
            Assert-Rejected -Name "formal build requires clean revision" -Arguments @(
                "install", "-Project", "memory-palace-test", "-EnvFile", $fakeEnvFile,
                "-SecretsVolume", "memory-palace-test-secrets"
            ) -ExpectedText @("clean Git worktree", "-AllowDirtyBuild")
        }
        finally {
            if ($null -eq $previousFakeGitDirty) { Remove-Item Env:MVP_FAKE_GIT_DIRTY -ErrorAction SilentlyContinue }
            else { $env:MVP_FAKE_GIT_DIRTY = $previousFakeGitDirty }
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) { Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog }
    }

    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $installOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath install -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" -AllowDirtyBuild 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "install command failed: $((@($installOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine)"
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $installText = (@($installOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    foreach ($sentinel in @("database-sentinel", "admin-sentinel", "jwt-sentinel")) {
        if ($installText.Contains($sentinel) -or $dockerText.Contains($sentinel)) {
            throw "install exposed deployment secret sentinel '$sentinel'."
        }
    }
    foreach ($expected in @(
        "volume create",
        "memory-palace-test-secrets",
        "pull postgres redis nginx",
        "build app",
        "pull alpine:3.20.10",
        "image inspect --format {{.Id}} memory-palace-test-app:latest",
        "image tag sha256:fake-app-image"
    )) {
        if (-not $dockerText.Contains($expected)) {
            throw "install did not invoke expected Docker operation '$expected'. Log: $dockerText"
        }
    }
    if (-not $installText.Contains("Release revision:")) {
        throw "install did not record the release HEAD. Output: $installText"
    }
    Write-Host "safe install lifecycle: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $startOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath start -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "start command failed: $((@($startOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine)"
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $startText = (@($startOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    foreach ($sentinel in @("database-sentinel", "admin-sentinel", "jwt-sentinel")) {
        if ($startText.Contains($sentinel) -or $dockerText.Contains($sentinel)) {
            throw "start exposed deployment secret sentinel '$sentinel'."
        }
    }
    $dependencyStart = $dockerText.IndexOf("up -d postgres redis")
    $migrationRun = $dockerText.IndexOf("run --rm --no-deps app python -c")
    $applicationStart = $dockerText.IndexOf("up -d --no-deps app")
    $nginxStart = $dockerText.IndexOf("up -d --no-deps nginx")
    if ($dependencyStart -lt 0 -or $migrationRun -le $dependencyStart -or
        $applicationStart -le $migrationRun -or $nginxStart -le $applicationStart) {
        throw "start did not preserve dependency -> migrate -> app -> nginx order. Log: $dockerText"
    }
    $startScriptSource = Get-Content -LiteralPath $ScriptPath -Raw -Encoding utf8
    foreach ($expected in @(
        "src.memory_palace.knowledge.db_init import init_database",
        "src.memory_palace.knowledge.postgres_client import PostgresDBClient",
        "mvp_schema_migrations"
    )) {
        if (-not $startScriptSource.Contains($expected)) {
            throw "start migration did not use formal PostgreSQL contract '$expected'."
        }
    }
    Write-Host "phased start with migration: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $previousRuntimeReady = $env:MVP_FAKE_RUNTIME_READY
    $previousNoHealthcheck = $env:MVP_FAKE_NO_HEALTHCHECK
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    $env:MVP_FAKE_RUNTIME_READY = "1"
    $env:MVP_FAKE_NO_HEALTHCHECK = "1"
    try {
        Assert-Rejected -Name "start requires healthchecks" -Arguments @(
            "start", "-Project", "memory-palace-test", "-EnvFile", $fakeEnvFile,
            "-SecretsVolume", "memory-palace-test-secrets"
        ) -ExpectedText @("healthcheck")
        Assert-Rejected -Name "doctor requires healthchecks" -Arguments @(
            "doctor", "-Project", "memory-palace-test", "-BackupRoot", $TestRoot
        ) -ExpectedText @("not-configured")
        Assert-Rejected -Name "verify requires healthchecks" -Arguments @(
            "verify", "-Project", "memory-palace-test", "-EnvFile", $fakeEnvFile,
            "-SecretsVolume", "memory-palace-test-secrets", "-BackupRoot", $TestRoot
        ) -ExpectedText @("not-configured")
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) { Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog }
        if ($null -eq $previousRuntimeReady) { Remove-Item Env:MVP_FAKE_RUNTIME_READY -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_RUNTIME_READY = $previousRuntimeReady }
        if ($null -eq $previousNoHealthcheck) { Remove-Item Env:MVP_FAKE_NO_HEALTHCHECK -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_NO_HEALTHCHECK = $previousNoHealthcheck }
    }
    Write-Host "mandatory service healthchecks: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $migrateOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath migrate -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "migrate command failed: $((@($migrateOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine)"
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    $postgresStart = $dockerText.IndexOf("up -d postgres")
    $migrationRun = $dockerText.IndexOf("run --rm --no-deps app python -c")
    if ($postgresStart -lt 0 -or $migrationRun -le $postgresStart) {
        throw "migrate did not start PostgreSQL before the formal migration. Log: $dockerText"
    }
    Write-Host "standalone PostgreSQL migration: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $previousRuntimeReady = $env:MVP_FAKE_RUNTIME_READY
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    $env:MVP_FAKE_RUNTIME_READY = "1"
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $verifyOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath verify -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" -BackupRoot $TestRoot 2>&1
        $verifyExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
        if ($null -eq $previousRuntimeReady) {
            Remove-Item Env:MVP_FAKE_RUNTIME_READY -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_RUNTIME_READY = $previousRuntimeReady
        }
    }
    $verifyText = (@($verifyOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($verifyExitCode -ne 0) {
        throw "verify command failed: $verifyText"
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    foreach ($expected in @(
        "exec app-test curl -fsS http://localhost:8000/health",
        "exec nginx-test wget -q -O /dev/null http://127.0.0.1/health",
        "exec nginx-test wget -q -O /dev/null http://127.0.0.1/admin/"
    )) {
        if (-not $dockerText.Contains($expected)) {
            throw "verify did not invoke '$expected'. Log: $dockerText"
        }
    }
    if (-not $verifyText.Contains("Doctor result: PASS") -or -not $verifyText.Contains("Verification result: PASS")) {
        throw "verify did not report doctor and verification success. Output: $verifyText"
    }
    foreach ($sentinel in @("database-sentinel", "admin-sentinel", "jwt-sentinel")) {
        if ($verifyText.Contains($sentinel) -or $dockerText.Contains($sentinel)) {
            throw "verify exposed deployment secret sentinel '$sentinel'."
        }
    }
    Write-Host "runtime and formal client verification: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $logsOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath logs -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "logs command failed: $((@($logsOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine)"
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $logsText = (@($logsOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    if (-not $dockerText.Contains("logs --no-color --tail 200") -or $dockerText.Contains("--follow")) {
        throw "logs must use a finite default tail without follow. Log: $dockerText"
    }
    if (-not $logsText.Contains("[REDACTED]")) {
        throw "logs did not emit redaction markers. Output: $logsText"
    }
    foreach ($sentinel in @("admin-sentinel", "token-sentinel", "sk-secret-sentinel")) {
        if ($logsText.Contains($sentinel)) {
            throw "logs exposed secret sentinel '$sentinel'."
        }
    }

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $followOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath logs -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" -Tail 50 -Follow -Service app 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "follow logs command failed."
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    if (-not $dockerText.Contains("logs --no-color --tail 50 --follow app")) {
        throw "logs did not enable explicit follow for the selected service. Log: $dockerText"
    }
    Write-Host "bounded and redacted logs: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    try {
        $stopOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath stop -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "stop command failed."
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    if (-not $dockerText.Contains(" -p memory-palace-test stop")) {
        throw "stop did not stop the Compose project. Log: $dockerText"
    }
    foreach ($forbidden in @(" down", "--volumes", "volume rm", "memory-palace-test-secrets target=")) {
        if ($dockerText.Contains($forbidden)) {
            throw "stop invoked destructive operation '$forbidden'. Log: $dockerText"
        }
    }
    Write-Host "data-preserving stop: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $previousRuntimeReady = $env:MVP_FAKE_RUNTIME_READY
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    $env:MVP_FAKE_RUNTIME_READY = "1"
    try {
        $upgradeOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath upgrade -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" -BackupRoot $TestRoot `
            -BackupId "upgrade-success" -AllowDirtyBuild 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "upgrade command failed: $((@($upgradeOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine)"
        }
    }
    finally {
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) {
            Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog
        }
        if ($null -eq $previousRuntimeReady) {
            Remove-Item Env:MVP_FAKE_RUNTIME_READY -ErrorAction SilentlyContinue
        }
        else {
            $env:MVP_FAKE_RUNTIME_READY = $previousRuntimeReady
        }
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    $backupOperation = $dockerText.IndexOf("pg_dump -Fc")
    $pullOperation = $dockerText.IndexOf("pull postgres redis nginx")
    $buildOperation = $dockerText.IndexOf("build app")
    $migrationOperation = $dockerText.LastIndexOf("run --rm --no-deps app python -c")
    $recreateOperation = $dockerText.IndexOf("up -d --no-deps --force-recreate app")
    $clientVerification = $dockerText.LastIndexOf("http://127.0.0.1/admin/")
    if ($backupOperation -lt 0 -or $pullOperation -le $backupOperation -or
        $buildOperation -le $pullOperation -or $migrationOperation -le $buildOperation -or
        $recreateOperation -le $migrationOperation -or $clientVerification -le $recreateOperation) {
        throw "upgrade did not preserve backup -> pull -> build -> migrate -> recreate -> verify order. Log: $dockerText"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $TestRoot "upgrade-success\manifest.json") -PathType Leaf)) {
        throw "upgrade did not create its pre-upgrade backup manifest."
    }
    Write-Host "backup-first verified upgrade: PASS"

    Clear-Content -LiteralPath $fakeDockerLog
    $previousPath = $env:PATH
    $previousFakeDockerLog = $env:MVP_FAKE_DOCKER_LOG
    $previousRuntimeReady = $env:MVP_FAKE_RUNTIME_READY
    $previousUpgradeFail = $env:MVP_FAKE_UPGRADE_FAIL
    $env:PATH = "$fakeBin;$previousPath"
    $env:MVP_FAKE_DOCKER_LOG = $fakeDockerLog
    $env:MVP_FAKE_RUNTIME_READY = "1"
    $env:MVP_FAKE_UPGRADE_FAIL = "1"
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $failedUpgradeOutput = & powershell -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
            -File $ScriptPath upgrade -Project "memory-palace-test" -EnvFile $fakeEnvFile `
            -SecretsVolume "memory-palace-test-secrets" -BackupRoot $TestRoot `
            -BackupId "upgrade-failure" -AllowDirtyBuild 2>&1
        $failedUpgradeExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorPreference
        $env:PATH = $previousPath
        if ($null -eq $previousFakeDockerLog) { Remove-Item Env:MVP_FAKE_DOCKER_LOG -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_DOCKER_LOG = $previousFakeDockerLog }
        if ($null -eq $previousRuntimeReady) { Remove-Item Env:MVP_FAKE_RUNTIME_READY -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_RUNTIME_READY = $previousRuntimeReady }
        if ($null -eq $previousUpgradeFail) { Remove-Item Env:MVP_FAKE_UPGRADE_FAIL -ErrorAction SilentlyContinue }
        else { $env:MVP_FAKE_UPGRADE_FAIL = $previousUpgradeFail }
    }
    $failedUpgradeText = (@($failedUpgradeOutput) | ForEach-Object { "$_" }) -join [Environment]::NewLine
    if ($failedUpgradeExitCode -eq 0) {
        throw "upgrade failure simulation expected a non-zero exit code."
    }
    foreach ($expected in @(
        "mvp.cmd restore",
        "-BackupId upgrade-failure",
        "-TargetProject memory-palace-test-rollback",
        "-TargetSecretsVolume memory-palace-test-rollback-secrets"
    )) {
        if (-not $failedUpgradeText.Contains($expected)) {
            throw "failed upgrade did not provide rollback text '$expected'. Output: $failedUpgradeText"
        }
    }
    $dockerText = "$(Get-Content -LiteralPath $fakeDockerLog -Raw)"
    if ($dockerText.Contains(" down") -or $dockerText.Contains("--volumes") -or $dockerText.Contains("volume rm")) {
        throw "failed upgrade automatically destroyed data resources. Log: $dockerText"
    }
    Write-Host "non-destructive upgrade failure guidance: PASS"

    Assert-Rejected -Name "positional restore backup id" -Arguments @(
        "restore", "backup-20260728", "-BackupRoot", $TestRoot
    ) -ExpectedText @("TargetProject")

    Assert-Rejected -Name "missing target project" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $TestRoot
    ) -ExpectedText @("TargetProject")

    Assert-Rejected -Name "backup id traversal" -Arguments @(
        "restore", "-BackupId", "..\outside", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore"
    ) -ExpectedText @("BackupId", "direct child")

    Assert-Rejected -Name "target confirmation mismatch" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-other"
    ) -ExpectedText @("ConfirmTarget")

    Assert-Rejected -Name "source overwrite without force" -Arguments @(
        "restore", "-Project", "memory-palace-mvp", "-BackupId", "backup-20260728",
        "-BackupRoot", $TestRoot, "-TargetProject", "memory-palace-mvp",
        "-ConfirmTarget", "memory-palace-mvp"
    ) -ExpectedText @("source project", "-Force")

    Assert-Rejected -Name "missing restore environment" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-restore"
    ) -ExpectedText @("EnvFile", "secret")

    Assert-Rejected -Name "missing isolated secrets volume" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-restore",
        "-EnvFile", (Join-Path $ProjectRoot ".env.example")
    ) -ExpectedText @("TargetSecretsVolume")

    Assert-Rejected -Name "shared global secrets volume" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-restore",
        "-EnvFile", (Join-Path $ProjectRoot ".env.example"),
        "-TargetSecretsVolume", "memory-palace-secrets"
    ) -ExpectedText @("TargetSecretsVolume", "shared")

    Assert-Rejected -Name "unsafe backup root" -Arguments @(
        "restore", "-BackupId", "backup-20260728", "-BackupRoot", $ProjectRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-restore",
        "-EnvFile", (Join-Path $ProjectRoot ".env.example"),
        "-TargetSecretsVolume", "memory-palace-restore-secrets"
    ) -ExpectedText @("dedicated directory")

    $tamperedBackup = Join-Path $TestRoot "tampered-backup"
    New-Item -ItemType Directory -Path $tamperedBackup | Out-Null
    Set-Content -LiteralPath (Join-Path $tamperedBackup "postgres.dump") -Value "not-a-real-dump" -Encoding utf8
    [ordered]@{
        schema_version = "memory-palace-mvp-backup/v3"
        backup_id = "tampered-backup"
        source = [ordered]@{ compose_project = "memory-palace-mvp"; compose_file_sha256 = ("0" * 64) }
        artifacts = [ordered]@{
            postgres = [ordered]@{
                file = "postgres.dump"
                bytes = (Get-Item -LiteralPath (Join-Path $tamperedBackup "postgres.dump")).Length
                sha256 = ("0" * 64)
            }
        }
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $tamperedBackup "manifest.json") -Encoding utf8

    Assert-Rejected -Name "tampered backup checksum" -Arguments @(
        "restore", "-BackupId", "tampered-backup", "-BackupRoot", $TestRoot,
        "-TargetProject", "memory-palace-restore", "-ConfirmTarget", "memory-palace-restore",
        "-EnvFile", (Join-Path $ProjectRoot ".env.example"),
        "-TargetSecretsVolume", "memory-palace-restore-secrets"
    ) -ExpectedText @("checksum mismatch")

    $scriptSource = Get-Content -LiteralPath $ScriptPath -Raw -Encoding utf8
    foreach ($requiredText in @(
        "function Write-BackupRecord",
        "INSERT INTO backup_records",
        '$previousErrorPreference = $ErrorActionPreference',
        '$BackupId.Replace("''", "''''")',
        '-Status "COMPLETED"',
        '$ManifestSchema = "memory-palace-mvp-backup/v3"',
        'Name = "PostgreSQL + pgvector"',
        '[string]$TargetSecretsVolume',
        '$env:MEMORY_PALACE_SECRETS_VOLUME = $TargetSecretsVolume',
        'Initialize-EmptySecretsVolume',
        'Initialize-RestoreApplicationSecret',
        '$env:DEEPSEEK_BASE_URL = "http://127.0.0.1:9/v1"'
    )) {
        if (-not $scriptSource.Contains($requiredText)) {
            throw "backup evidence contract is missing '$requiredText'."
        }
    }
    Write-Host "completed backup evidence: PASS"
}
finally {
    $resolvedTestRoot = [System.IO.Path]::GetFullPath($TestRoot)
    $testParent = [System.IO.Directory]::GetParent($resolvedTestRoot)
    if ($testParent -and
        [string]::Equals($testParent.FullName.TrimEnd('\'), $SystemTemp.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedTestRoot).StartsWith("memory-palace-mvp-tests-")) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
