# Shared helpers for the scenic demo entry scripts.
# This file is dot-sourced; it never prints secrets.

Set-StrictMode -Version Latest

$script:ScenicRepoRoot = Split-Path -Parent $PSScriptRoot
$script:ScenicComposeFile = Join-Path $script:ScenicRepoRoot 'deploy\docker-compose.yml'
$script:ScenicEnvFile = Join-Path $script:ScenicRepoRoot '.env'
$script:ScenicProjectName = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'memory-palace-scenic' }

function Read-ScenicDotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Key)

    if (-not (Test-Path -LiteralPath $script:ScenicEnvFile)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $script:ScenicEnvFile -Encoding utf8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -le 0) { continue }
        if ($trimmed.Substring(0, $separator).Trim() -ne $Key) { continue }
        return $trimmed.Substring($separator + 1).Trim().Trim('"').Trim("'")
    }
    return $null
}

function Get-ScenicDemoHttpPort {
    if ($env:HTTP_PORT) { return [int]$env:HTTP_PORT }
    $configured = Read-ScenicDotEnvValue -Key 'HTTP_PORT'
    if ($configured) { return [int]$configured }
    return 8090
}

function Get-ScenicDemoBaseUrl {
    if ($env:SCENIC_DEMO_BASE_URL) { return $env:SCENIC_DEMO_BASE_URL.TrimEnd('/') }
    return "http://127.0.0.1:$(Get-ScenicDemoHttpPort)"
}

function Get-ScenicModelCache {
    param([string]$Override)

    $candidate = $Override
    if (-not $candidate) { $candidate = $env:BGE_M3_CACHE_DIR }
    if (-not $candidate) { $candidate = Read-ScenicDotEnvValue -Key 'BGE_M3_CACHE_DIR' }
    if (-not $candidate) {
        throw 'BGE_M3_CACHE_DIR is not set. Pass -ModelCache or set it in .env.'
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
    if (-not (Test-Path -LiteralPath $expanded -PathType Container)) {
        throw "BGE_M3 model cache does not exist: $expanded"
    }
    return (Resolve-Path -LiteralPath $expanded).Path
}

function Assert-ScenicDocker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI was not found. Start Docker Desktop first.'
    }
    & docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Desktop is not running or the Docker daemon is unavailable.'
    }
    & docker compose version --short *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is required.'
    }
}

function Invoke-ScenicCompose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    Assert-ScenicDocker
    Push-Location $script:ScenicRepoRoot
    try {
        & docker compose -p $script:ScenicProjectName --env-file $script:ScenicEnvFile -f $script:ScenicComposeFile --profile agent-runtime --profile tracing @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}


function Wait-ScenicAppContainerHealthy {
    param([int]$TimeoutSeconds = 360)

    $container = "$($script:ScenicProjectName)-app-1"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $container 2>$null)
        if ($LASTEXITCODE -eq 0 -and $status -and $status.Trim() -eq 'healthy') {
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Scenic app container did not become healthy within $TimeoutSeconds seconds."
}

function Wait-ScenicDemoHealth {
    param([int]$TimeoutSeconds = 360)

    $baseUrl = Get-ScenicDemoBaseUrl
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 3
            if ($health.status -in @('ok', 'healthy')) {
                return $health
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    throw "Scenic demo did not become healthy at $baseUrl/health within $TimeoutSeconds seconds."
}

function Get-ScenicDemoContainer {
    $container = "$($script:ScenicProjectName)-app-1"
    $name = & docker ps --filter "name=^/$container$" --format '{{.Names}}'
    if ($LASTEXITCODE -ne 0 -or -not $name) {
        throw "Scenic app container is not running: $container"
    }
    return $container.Trim()
}

function Get-ScenicDemoPassword {
    foreach ($name in @('SCENIC_DEMO_PASSWORD', 'SCENIC_ACCOUNT_PASSWORD', 'SCENIC_E2E_PASSWORD')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and $value.Trim()) { return $value.Trim() }
    }
    $container = Get-ScenicDemoContainer
    $value = (& docker exec $container sh -c 'cat /run/memory-palace-secrets/scenic_account_password').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $value) {
        throw 'The scenic demo password is missing. Run scripts\set_scenic_account_secret.ps1 first.'
    }
    return $value
}

function Assert-ScenicDemoSecrets {
    $container = Get-ScenicDemoContainer
    & docker exec $container sh -c 'test -s /run/memory-palace-secrets/deepseek_api_key && test -s /run/memory-palace-secrets/scenic_account_password'
    if ($LASTEXITCODE -ne 0) {
        throw 'Demo secrets are incomplete. Set deepseek_api_key and scenic_account_password in memory-palace-secrets.'
    }
}
