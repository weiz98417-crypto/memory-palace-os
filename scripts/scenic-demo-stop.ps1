[CmdletBinding()]
param(
    [string]$ModelCache = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scenic-demo-common.ps1')

# Compose still interpolates the model cache during config resolution.
if (-not $env:BGE_M3_CACHE_DIR) {
    $configuredCache = Read-ScenicDotEnvValue -Key 'BGE_M3_CACHE_DIR'
    if ($configuredCache) { $env:BGE_M3_CACHE_DIR = $configuredCache }
}
if ($ModelCache) { $env:BGE_M3_CACHE_DIR = $ModelCache }
Invoke-ScenicCompose -Arguments @('down')

Write-Host 'Scenic demo stack stopped. PostgreSQL, Redis, Hatchet and attachment volumes were preserved.' -ForegroundColor Green
