[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scenic-demo-common.ps1')

Assert-ScenicDocker

Write-Host 'Compose services:' -ForegroundColor Cyan
Invoke-ScenicCompose -Arguments @('ps')

$baseUrl = Get-ScenicDemoBaseUrl
Write-Host ''
Write-Host "Checking $baseUrl/health ..." -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 5
    Write-Host ("Health: {0} | queue_depth: {1}" -f $health.status, $health.queue_depth) -ForegroundColor Green
}
catch {
    Write-Warning "Health check failed: $($_.Exception.Message)"
}

try {
    $container = Get-ScenicDemoContainer
    & docker exec $container sh -c 'test -s /run/memory-palace-secrets/deepseek_api_key'
    if ($LASTEXITCODE -eq 0) { Write-Host 'DeepSeek key: present' -ForegroundColor Green } else { Write-Warning 'DeepSeek key: missing' }
    & docker exec $container sh -c 'test -s /run/memory-palace-secrets/scenic_account_password'
    if ($LASTEXITCODE -eq 0) { Write-Host 'Demo password: present' -ForegroundColor Green } else { Write-Warning 'Demo password: missing' }
}
catch {
    Write-Warning $_.Exception.Message
}

Write-Host ''
Write-Host 'Entry points:' -ForegroundColor Cyan
Write-Host "  Operations prep : $baseUrl/operations/scenic/"
Write-Host "  Command center  : $baseUrl/admin/"
Write-Host "  Field assistant : $baseUrl/assistant/"
Write-Host "  WeCom simulator : $baseUrl/simulator/wecom/"
Write-Host "  Hatchet UI      : http://127.0.0.1:8091/"
Write-Host "  Jaeger UI       : http://127.0.0.1:16686/"
