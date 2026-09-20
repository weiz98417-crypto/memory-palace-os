[CmdletBinding()]
param(
    [ValidateSet('Open', 'Verify', 'Auto')]
    [string]$Mode = 'Open',
    [string]$Browser = 'msedge',
    [int]$KeepOpenSeconds = 0
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scenic-demo-common.ps1')

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found. Install uv before opening the demo.'
}

$baseUrl = Get-ScenicDemoBaseUrl
$health = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 5
if ($health.status -notin @('ok', 'healthy')) {
    throw "Scenic demo is not healthy: $baseUrl/health"
}

$password = Get-ScenicDemoPassword
$env:SCENIC_DEMO_PASSWORD = $password
$env:SCENIC_DEMO_BASE_URL = $baseUrl

Push-Location $script:ScenicRepoRoot
try {
    if ($Mode -eq 'Auto') {
        & uv run --with playwright python scripts\scenic_auto_demo.py --base-url $baseUrl --browser-channel $Browser --headless
    }
    elseif ($Mode -eq 'Verify') {
        & uv run --with playwright python scripts\scenic_demo_launcher.py --base-url $baseUrl --browser-channel $Browser --headless --verify-only
    }
    else {
        $arguments = @(
            'run', '--with', 'playwright', 'python',
            'scripts\scenic_demo_launcher.py',
            '--base-url', $baseUrl,
            '--browser-channel', $Browser
        )
        if ($KeepOpenSeconds -gt 0) {
            $arguments += @('--keep-open', [string]$KeepOpenSeconds)
        }
        & uv @arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Demo command failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
