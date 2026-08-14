# LarkNova M6 demo.
# Rebuilds the deterministic synthetic corpus, runs the full golden evaluation
# and prints the persisted report in data/reports/resume_metrics.json.

[CmdletBinding()]
param(
    [string]$Database = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not $Database) {
    $Database = Join-Path $Root 'data\synth.db'
}

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'bootstrap.ps1')
if ($LASTEXITCODE -ne 0) {
    throw 'bootstrap.ps1 failed'
}

Write-Host '== seed synthetic corpus =='
& python -m feishu_agent.main --db $Database synthetic seed --messages 0 --reset-derived
if ($LASTEXITCODE -ne 0) {
    throw 'synthetic seed failed'
}

Write-Host '== run golden evaluation =='
& python -m feishu_agent.main --db $Database eval run --mode rule --limit 0
if ($LASTEXITCODE -ne 0) {
    throw 'eval run failed'
}

Write-Host '== persisted report =='
& python -m feishu_agent.main --db $Database eval report
if ($LASTEXITCODE -ne 0) {
    throw 'eval report failed'
}

Write-Host 'Demo complete. See docs\DEMO.md for the acceptance walkthrough.'
exit 0
