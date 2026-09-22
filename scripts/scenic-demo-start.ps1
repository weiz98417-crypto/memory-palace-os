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
if (-not $env:OTEL_EXPORTER_OTLP_ENDPOINT) { $env:OTEL_EXPORTER_OTLP_ENDPOINT = 'http://jaeger:4317' }

# Docker Desktop can assign a different bridge gateway after a network recreate.
# The protected operations entry trusts the local ingress, so keep this value in sync.
$gateway = Get-ScenicEgressGateway
if ($gateway) { $env:SCENIC_PREP_ALLOWED_HOSTS = Merge-ScenicAllowedHosts -Gateway $gateway }

$arguments = @('up', '-d')
if (-not $NoBuild) { $arguments += '--build' }
$arguments += @('app', 'nginx', 'scenic-agent-worker', 'hatchet-api', 'hatchet-dashboard', 'jaeger')

Write-Host "Starting scenic demo stack ($script:ScenicProjectName)..." -ForegroundColor Cyan
Invoke-ScenicCompose -Arguments $arguments
Wait-ScenicAppContainerHealthy -TimeoutSeconds $TimeoutSeconds

# On a cold start the network is created by the command above. Re-read its gateway
# and apply it to the app before opening the protected operations entry.
$gateway = Get-ScenicEgressGateway
if ($gateway) {
    $allowedHosts = Merge-ScenicAllowedHosts -Gateway $gateway
    if ($env:SCENIC_PREP_ALLOWED_HOSTS -ne $allowedHosts) {
        $env:SCENIC_PREP_ALLOWED_HOSTS = $allowedHosts
        Invoke-ScenicCompose -Arguments @('up', '-d', '--no-deps', '--force-recreate', 'app')
        Wait-ScenicAppContainerHealthy -TimeoutSeconds $TimeoutSeconds
    }
}

# Recreate nginx upstream resolution after the app container is recreated.
Invoke-ScenicCompose -Arguments @('restart', 'nginx')
$health = Wait-ScenicDemoHealth -TimeoutSeconds $TimeoutSeconds
Assert-ScenicDemoSecrets

$baseUrl = Get-ScenicDemoBaseUrl
Write-Host ''
Write-Host "Scenic demo is ready: $baseUrl/" -ForegroundColor Green
Write-Host "Health: $($health.status) | queue_depth: $($health.queue_depth)"
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1"
