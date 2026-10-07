[CmdletBinding()]
param(
    [string]$OutputDirectory = [Environment]::GetFolderPath('Desktop'),
    [string]$Stamp = '20260929'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$packageName = "memory-palace-os-source-$Stamp"
$stage = Join-Path $env:TEMP "$packageName-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$zip = Join-Path $OutputDirectory "$packageName.zip"
$sha = "$zip.sha256"

if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
if (Test-Path -LiteralPath $sha) { Remove-Item -LiteralPath $sha -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

$rootFiles = @(
    '.dockerignore', '.env.example', 'AGENTS.md', 'CLAUDE.md', 'CHANGELOG.md', 'CONTEXT.md',
    'LICENSE', 'README.md', 'REPRODUCE.md', 'main.py', 'pyproject.toml', 'requirements.txt',
    'requirements.lock', 'requirements-eval.txt', 'requirements-scenic-agent-eval.txt',
    'requirements-scenic-agent-local-embeddings.txt', 'requirements-scenic-agent-prototype.txt',
    'run.sh', 'uv.lock'
)

foreach ($relative in $rootFiles) {
    $source = Join-Path $root $relative
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        $target = Join-Path $stage $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target
    }
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [string[]]$ExcludedDirectories = @(),
        [string[]]$ExcludedFiles = @()
    )

    $source = Join-Path $root $RelativePath
    $target = Join-Path $stage $RelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { return }
    $excludedDirectoryNames = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($directory in @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache')) {
        [void]$excludedDirectoryNames.Add($directory)
    }
    foreach ($directory in $ExcludedDirectories) {
        [void]$excludedDirectoryNames.Add($directory)
    }

    function Copy-FilteredDirectory {
        param([string]$SourceDirectory, [string]$TargetDirectory)
        New-Item -ItemType Directory -Path $TargetDirectory -Force | Out-Null
        foreach ($item in Get-ChildItem -LiteralPath $SourceDirectory -Force) {
            if ($item.PSIsContainer) {
                if ($excludedDirectoryNames.Contains($item.Name)) { continue }
                Copy-FilteredDirectory $item.FullName (Join-Path $TargetDirectory $item.Name)
                continue
            }
            $skip = $false
            foreach ($pattern in $ExcludedFiles) {
                if ($item.Name -like $pattern) { $skip = $true; break }
            }
            if (-not $skip) {
                Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $TargetDirectory $item.Name)
            }
        }
    }

    Copy-FilteredDirectory $source $target
}

Copy-Tree 'src'
Copy-Tree 'scripts'
Copy-Tree 'tests' @('__pycache__', '.pytest_cache') @('*.pyc', '*.pyo')
Copy-Tree 'evals' @('__pycache__') @('*.pyc', '*.pyo')
Copy-Tree 'frontend' @('node_modules', '.scratch', 'test-results', 'coverage') @('*.pyc', '*.pyo')
Copy-Tree 'static' @('client')
Copy-Tree 'deploy'
Copy-Tree 'docs' @('__pycache__') @('*.pyc', '*.pyo')
Copy-Tree 'openspec'
Copy-Tree '.claude' @() @('settings.local.json')
Copy-Tree 'artifacts/knowledge'
Copy-Tree 'artifacts/scenic-agent-eval'

$manifest = [ordered]@{
    package = $packageName
    generated_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    git_head = (& git -C $root rev-parse HEAD).Trim()
    git_branch = (& git -C $root branch --show-current).Trim()
    working_tree = 'snapshot of current working tree; uncommitted changes included'
    included = @(
        'source: src, scripts, main.py', 'tests', 'evals/scenic_agent', 'artifacts/knowledge',
        'artifacts/scenic-agent-eval', 'Docker deployment', 'frontend source', 'static assets',
        'docs, openspec, UAT evidence', 'AGENTS.md, CLAUDE.md, REPRODUCE.md'
    )
    excluded = @(
        '.env and local secrets', 'data/ database and logs', 'Docker/Node/Python caches',
        'frontend/node_modules', 'model caches', 'graphify-out and scratch output', 'local Claude settings'
    )
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stage 'PACKAGE_MANIFEST.json') -Encoding UTF8

$checksums = Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    "{0}  {1}" -f $hash.Hash, $_.FullName.Substring($stage.Length + 1)
}
$checksums | Set-Content -LiteralPath (Join-Path $stage 'SHA256SUMS.txt') -Encoding UTF8

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal -Force
$zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
"$zipHash  $(Split-Path $zip -Leaf)" | Set-Content -LiteralPath $sha -Encoding ASCII

[pscustomobject]@{
    zip = $zip
    sha256_file = $sha
    sha256 = $zipHash
    bytes = (Get-Item -LiteralPath $zip).Length
    files = (Get-ChildItem -LiteralPath $stage -Recurse -File | Measure-Object).Count
    staging_directory = $stage
} | ConvertTo-Json
