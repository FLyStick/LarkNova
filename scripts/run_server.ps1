# LarkNova HTTP API launcher.
# Reads credentials from .env, uses the local SQLite database and starts
# /api/agent/* with auth and rate limiting when configured.

[CmdletBinding()]
param(
    [string]$Database = '',
    [string]$ListenHost = '127.0.0.1',
    [int]$Port = 8080,
    [int]$Interval = 60,
    [string]$Identity = 'user',
    [switch]$SyncOnStart
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not $Database) {
    $Database = Join-Path $Root 'data\agent.db'
}

$pythonArgs = @(
    '--db', $Database,
    'serve',
    '--host', $ListenHost,
    '--port', [string]$Port,
    '--interval', [string]$Interval,
    '--identity', $Identity
)
if ($SyncOnStart) {
    $pythonArgs += '--sync-on-start'
}

Write-Host "Starting LarkNova on http://${ListenHost}:${Port} (identity=${Identity}, interval=${Interval}s)"
& python -m feishu_agent.main @pythonArgs
exit $LASTEXITCODE
