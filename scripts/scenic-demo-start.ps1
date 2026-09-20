[CmdletBinding()]
param(
    [string]$ModelCache = '',
    [switch]$NoBuild,
    [int]$TimeoutSeconds = 360
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scenic-demo-common.ps1')

$cache = Get-ScenicModelCache -Override $ModelCache
$env:BGE_M3_CACHE_DIR = $cache
Assert-ScenicDocker

$arguments = @('up', '-d')
if (-not $NoBuild) { $arguments += '--build' }
$arguments += @('app', 'nginx', 'scenic-agent-worker', 'hatchet-api', 'jaeger')

Write-Host "Starting scenic demo stack ($script:ScenicProjectName)..." -ForegroundColor Cyan
Invoke-ScenicCompose -Arguments $arguments
Wait-ScenicAppContainerHealthy -TimeoutSeconds $TimeoutSeconds
# Recreate nginx upstream resolution after the app container is recreated.
Invoke-ScenicCompose -Arguments @('restart', 'nginx')
$health = Wait-ScenicDemoHealth -TimeoutSeconds $TimeoutSeconds
Assert-ScenicDemoSecrets

$baseUrl = Get-ScenicDemoBaseUrl
Write-Host ''
Write-Host "Scenic demo is ready: $baseUrl/" -ForegroundColor Green
Write-Host "Health: $($health.status) | queue_depth: $($health.queue_depth)"
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1"
