[CmdletBinding()]
param(
    [ValidateSet('Full', 'Start', 'Verify', 'Auto', 'Status', 'Stop')]
    [string]$Mode = 'Full',
    [string]$Browser = 'msedge',
    [string]$ModelCache = '',
    [int]$TimeoutSeconds = 360,
    [switch]$Build,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scenic-demo-common.ps1')

function Test-ScenicDemoRoutes {
    $baseUrl = Get-ScenicDemoBaseUrl
    foreach ($route in @('/admin/', '/assistant/', '/operations/scenic/', '/operations/evaluation/', '/simulator/wecom/')) {
        $response = Invoke-WebRequest -Uri "$baseUrl$route" -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -ge 500) { throw "Demo route failed: $route returned $($response.StatusCode)" }
        Write-Host ("  {0,-28} HTTP {1}" -f $route, $response.StatusCode) -ForegroundColor Green
    }
}

function Write-ScenicDemoGuide {
    $baseUrl = Get-ScenicDemoBaseUrl
    Write-Host ''
    Write-Host '========================= 景区演示入口 =========================' -ForegroundColor Cyan
    Write-Host "运行准备（模拟输入与时钟） : $baseUrl/operations/scenic/"
    Write-Host "指挥中心（王芳）             : $baseUrl/admin/"
    Write-Host "现场端（陈雨/李明）          : $baseUrl/assistant/"
    Write-Host "内部通知与回执              : $baseUrl/simulator/wecom/"
    Write-Host 'Hatchet 运行历史             : http://127.0.0.1:8091/'
    Write-Host 'Jaeger 链路追踪              : http://127.0.0.1:16686/'
    Write-Host ''
    Write-Host '角色账号：simulation-ops / wangfang / chenyu / liming / knowledge-owner' -ForegroundColor Yellow
    Write-Host '密码由 memory-palace-secrets 卷统一提供，开窗脚本会自动登录，不会打印密码。'
    Write-Host ''
    Write-Host '15 步人工演示流程：' -ForegroundColor Cyan
    Write-Host ' 1. 运行准备：准备新运行，确认场景为 PAUSED。'
    Write-Host ' 2. 运行准备：到设备异常，产生 12 号观光车右后轮告警。'
    Write-Host ' 3. 指挥中心：转为 P1 事件，记录业务编号和事件状态。'
    Write-Host ' 4. 现场端李明：提交现场说明和右后轮照片。'
    Write-Host ' 5. 指挥中心：检索并核验 SOP，确认来源为已发布 SOP。'
    Write-Host ' 6. 指挥中心：生成正式任务，确认检修任务与高风险审批。'
    Write-Host ' 7. 指挥中心：批准审批，确认执行状态为 SUCCEEDED。'
    Write-Host ' 8. 现场端陈雨：开始检修任务，事件进入 ACKNOWLEDGED。'
    Write-Host ' 9. 现场端陈雨：提交结构化检修结果。'
    Write-Host '10. 运行准备：到东门客流，产生 EAST_GATE_CAPACITY 告警。'
    Write-Host '11. 指挥中心：追加分流任务，分派给李明。'
    Write-Host '12. 现场端李明：开始并完成分流任务。'
    Write-Host '13. 运行准备：到风险恢复，确认告警全部 RECOVERED。'
    Write-Host '14. 指挥中心：核验并解除风险，然后关闭并形成审计卷宗。'
    Write-Host '15. 内部通知：检查每条任务回执为 RECEIPT_RECORDED。'
    Write-Host ''
    Write-Host '自动验收命令：' -ForegroundColor Cyan
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-full.ps1 -Mode Auto'
    Write-Host '  powershell -ExecutionPolicy Bypass -File .\scripts\scenic-demo-open.ps1 -Mode Verify'
    Write-Host ''
    Write-Host '证据目录：' -ForegroundColor Cyan
    Write-Host '  artifacts\scenic-e2e\auto-demo'
    Write-Host '  artifacts\scenic-e2e\console-visual'
    Write-Host '  artifacts\scenic-agent-eval'
    Write-Host '================================================================'
}

switch ($Mode) {
    'Stop' {
        & (Join-Path $PSScriptRoot 'scenic-demo-stop.ps1') -ModelCache $ModelCache
        return
    }
    'Status' {
        & (Join-Path $PSScriptRoot 'scenic-demo-status.ps1')
        return
    }
    'Verify' {
        Assert-ScenicDocker
        $env:FRONTEND_V2_APPS = 'console,field,integration,operations'
        if ($Build) {
            & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -TimeoutSeconds $TimeoutSeconds
        }
        else {
            & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -NoBuild -TimeoutSeconds $TimeoutSeconds
        }
        Wait-ScenicDemoHealth -TimeoutSeconds $TimeoutSeconds | Out-Null
        Assert-ScenicDemoSecrets
        Test-ScenicDemoRoutes
        & (Join-Path $PSScriptRoot 'scenic-demo-open.ps1') -Mode Verify -Browser $Browser
        return
    }
    'Auto' {
        Assert-ScenicDocker
        $env:FRONTEND_V2_APPS = 'console,field,integration,operations'
        if ($Build) {
            & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -TimeoutSeconds $TimeoutSeconds
        }
        else {
            & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -NoBuild -TimeoutSeconds $TimeoutSeconds
        }
        Wait-ScenicDemoHealth -TimeoutSeconds $TimeoutSeconds | Out-Null
        Assert-ScenicDemoSecrets
        & (Join-Path $PSScriptRoot 'scenic-demo-open.ps1') -Mode Auto -Browser $Browser
        return
    }
}

Assert-ScenicDocker
$env:FRONTEND_V2_APPS = 'console,field,integration,operations'

if ($Build) {
    & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -TimeoutSeconds $TimeoutSeconds
}
else {
    & (Join-Path $PSScriptRoot 'scenic-demo-start.ps1') -ModelCache $ModelCache -NoBuild -TimeoutSeconds $TimeoutSeconds
}

$health = Wait-ScenicDemoHealth -TimeoutSeconds $TimeoutSeconds
Assert-ScenicDemoSecrets
Test-ScenicDemoRoutes
Write-Host ''
Write-Host "系统健康：$($health.status) | 队列深度：$($health.queue_depth)" -ForegroundColor Green

if (-not $NoOpen) {
    & (Join-Path $PSScriptRoot 'scenic-demo-open.ps1') -Mode Open -Browser $Browser
}
Write-ScenicDemoGuide
