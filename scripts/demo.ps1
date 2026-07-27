[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "reset", "verify", "logs", "status")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $ProjectRoot "deploy\docker-compose.demo.yml"
$ComposeArgs = @("compose", "-f", $ComposeFile)
$DemoPort = if ($env:DEMO_PORT) { $env:DEMO_PORT } else { "8000" }
$BaseUrl = "http://localhost:$DemoPort"
$ScenarioEvidencePath = Join-Path $ProjectRoot "docs\verification\enterprise-demo-v1\scenario-results.json"

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & docker @ComposeArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE."
    }
}

function Test-DockerEnvironment {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install or start Docker Desktop."
    }

    & docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running or the Docker daemon is unavailable."
    }

    & docker compose version --short *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is required."
    }

    $parsedPort = 0
    if (-not [int]::TryParse($DemoPort, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
        throw "DEMO_PORT must be a number between 1 and 65535."
    }
}

function Test-DemoPort {
    $runningServices = & docker @ComposeArgs ps --services --status running 2>$null
    if ($LASTEXITCODE -eq 0 -and $runningServices -contains "app") {
        return
    }

    $listener = Get-NetTCPConnection -LocalPort ([int]$DemoPort) -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $DemoPort is already in use. Set DEMO_PORT to another port before starting the demo."
    }
}

function Wait-DemoHealth {
    $deadline = (Get-Date).AddSeconds(90)
    do {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 3
            if ($health.status -in @("ok", "healthy")) {
                Write-Host "Demo is ready at $BaseUrl/demo"
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    Invoke-Compose -Arguments @("logs", "--tail", "80", "app")
    throw "Demo did not become healthy within 90 seconds."
}

function Invoke-DemoApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("Get", "Post")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body
    )

    $request = @{
        Method     = $Method
        Uri        = "$BaseUrl$Path"
        TimeoutSec = 10
    }
    if ($null -ne $Body) {
        $request.ContentType = "application/json"
        $request.Body = $Body | ConvertTo-Json -Depth 10 -Compress
    }
    Invoke-RestMethod @request
}

function Test-LiveScenarios {
    $scenarioIds = @(
        "emergency-p0",
        "knowledge-rain",
        "persona-mentor",
        "weekend-night-plan"
    )
    $results = @()

    foreach ($scenarioId in $scenarioIds) {
        $initial = Invoke-DemoApi -Method Post -Path "/demo/scenarios/$scenarioId/runs" -Body @{}
        $reset = Invoke-DemoApi -Method Post -Path "/demo/runs/$($initial.run_id)/actions" -Body @{
            action           = "reset"
            expected_version = $initial.version
        }
        $run = Invoke-DemoApi -Method Post -Path "/demo/runs/$($reset.run_id)/actions" -Body @{
            action           = "play"
            expected_version = $reset.version
        }

        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 200
            $run = Invoke-DemoApi -Method Get -Path "/demo/runs/$($run.run_id)"
        } while ($run.status -eq "RUNNING" -and (Get-Date) -lt $deadline)

        if ($run.status -ne "COMPLETED") {
            throw "Live scenario $scenarioId ended in $($run.status), expected COMPLETED."
        }

        $report = Invoke-DemoApi -Method Get -Path "/demo/runs/$($run.run_id)/report"
        $evidence = @($report.run.steps)
        $nonDemoEvidence = @($evidence | Where-Object { $_.execution_mode -ne "DEMO_ADAPTER" })
        if ($report.schema_version -ne "enterprise-demo-report/v1" -or $nonDemoEvidence.Count -gt 0) {
            throw "Live scenario $scenarioId returned an invalid or non-demo report."
        }

        $failedAttempts = @($evidence | Where-Object { $_.status -eq "FAILED" })
        $retryTotal = ($evidence | Measure-Object -Property retry_count -Sum).Sum
        if ($null -eq $retryTotal) {
            $retryTotal = 0
        }
        $recoveryContract = @(
            $evidence |
                Where-Object { $_.step_id -eq "recover-equipment-check" } |
                ForEach-Object {
                    [ordered]@{
                        step_id = $_.step_id
                        attempt = $_.attempt
                        status  = $_.status
                    }
                }
        )
        $results += [ordered]@{
            scenario_id      = $scenarioId
            run_id           = $run.run_id
            trace_id         = $run.trace_id
            status           = $run.status
            completed_steps  = $run.progress.completed
            total_steps      = $run.progress.total
            evidence_count   = $report.evidence_count
            elapsed_ms       = $run.elapsed_ms
            failed_attempts  = $failedAttempts.Count
            retries          = [int]$retryTotal
            recovery_contract = $recoveryContract
        }

        $finalReset = Invoke-DemoApi -Method Post -Path "/demo/runs/$($run.run_id)/actions" -Body @{
            action           = "reset"
            expected_version = $run.version
        }
        if ($finalReset.status -ne "IDLE") {
            throw "Live scenario $scenarioId could not be returned to IDLE."
        }

        $recoveryLabel = if ($failedAttempts.Count -gt 0) { " (fixed failure recovered)" } else { "" }
        Write-Host "  $scenarioId`: PASS$recoveryLabel"
    }

    $evidenceDocument = [ordered]@{
        verification_date = (Get-Date).ToString("yyyy-MM-dd")
        generated_at      = (Get-Date).ToUniversalTime().ToString("o")
        environment       = "Docker Desktop / memory-palace-os:demo"
        execution_mode    = "DEMO_ADAPTER"
        results           = $results
    }
    $evidenceDirectory = Split-Path -Parent $ScenarioEvidencePath
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    $evidenceDocument | ConvertTo-Json -Depth 10 | Set-Content -Path $ScenarioEvidencePath -Encoding utf8
}

Test-DockerEnvironment

switch ($Action) {
    "start" {
        Test-DemoPort
        Invoke-Compose -Arguments @("up", "--build", "--detach")
        Wait-DemoHealth
    }
    "stop" {
        Invoke-Compose -Arguments @("down")
    }
    "reset" {
        Invoke-Compose -Arguments @("down", "--volumes", "--remove-orphans")
        Invoke-Compose -Arguments @("up", "--detach")
        Wait-DemoHealth
        Write-Host "Demo data was reset to a clean volume."
    }
    "verify" {
        Wait-DemoHealth
        Invoke-Compose -Arguments @("ps")
        $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 5
        Write-Host "Health: $($health.status) | queue: $($health.queue_depth)/$($health.queue_capacity)"
        Write-Host "Live scenario results:"
        Test-LiveScenarios
        Invoke-Compose -Arguments @(
            "run", "--rm", "--no-deps", "--volume", "/app/data", "app",
            "pytest", "-q", "-p", "no:cacheprovider", "--cov-report=term"
        )
        Write-Host "Automated tests: PASS (see pytest summary above)"
        Write-Host "Evidence report: $ScenarioEvidencePath"
    }
    "logs" {
        Invoke-Compose -Arguments @("logs", "--tail", "160", "--follow", "app")
    }
    "status" {
        Invoke-Compose -Arguments @("ps")
    }
}
