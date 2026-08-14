# LarkNova M6 bootstrap.
# Prepares local data directories and creates .env from .env.example.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvExample = Join-Path $Root '.env.example'
$EnvFile = Join-Path $Root '.env'

foreach ($Rel in @('data', 'data\reports')) {
    $Dir = Join-Path $Root $Rel
    if (-not (Test-Path -LiteralPath $Dir)) {
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        Write-Host ("created {0}" -f $Dir)
    }
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    if (-not (Test-Path -LiteralPath $EnvExample)) {
        throw '.env.example not found'
    }
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Host '.env created from .env.example; edit credentials before syncing.'
} else {
    Write-Host '.env already exists; keeping current configuration.'
}

Write-Host 'bootstrap complete. Next: scripts\demo.ps1, or CLI commands in README.md.'
exit 0
