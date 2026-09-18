[CmdletBinding()]
param(
    [ValidateSet("prepare-model", "start", "stop", "doctor")]
    [string]$Command = "doctor",
    [string]$ModelCache = $env:BGE_M3_CACHE_DIR
)

$root = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $root "deploy/docker-compose.yml"
if (-not $ModelCache) { throw "Set BGE_M3_CACHE_DIR to an absolute host directory" }
$resolvedCache = [IO.Path]::GetFullPath($ModelCache)
if ($Command -eq "prepare-model") {
    uv run --with "sentence-transformers>=3,<4" python (Join-Path $root "scripts/prepare_bge_m3.py") --cache-dir $resolvedCache
    exit $LASTEXITCODE
}
if ($Command -eq "start") {
    if (-not (Test-Path -LiteralPath (Join-Path $root ".env"))) { throw "Create .env from .env.example first" }
    if (-not (Test-Path -LiteralPath $resolvedCache)) { throw "Model cache is missing; run prepare-model first" }
    $env:BGE_M3_CACHE_DIR = $resolvedCache
    docker compose --env-file (Join-Path $root ".env") -f $compose up -d --build
    exit $LASTEXITCODE
}
if ($Command -eq "stop") {
    $env:BGE_M3_CACHE_DIR = $resolvedCache
    docker compose --env-file (Join-Path $root ".env") -f $compose down
    exit $LASTEXITCODE
}
$env:BGE_M3_CACHE_DIR = $resolvedCache
docker compose --env-file (Join-Path $root ".env") -f $compose config --quiet
if ($LASTEXITCODE -ne 0) { throw "Docker Compose configuration is invalid" }
docker compose --env-file (Join-Path $root ".env") -f $compose ps
