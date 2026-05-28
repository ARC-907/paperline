# run_pipeline.ps1 -- Rebuild the entire derived layer from on-disk evidence.
#
# Order matches system/tools/README.md. Each step is idempotent.
# Skips capture (step 0) -- run that on its own when you want fresh mail.
#
# Usage:
#   .\run_pipeline.ps1                 # full rebuild
#   .\run_pipeline.ps1 -SkipVerify     # skip the (slow) re-hash step
#   .\run_pipeline.ps1 -OnlyRender     # just regenerate Obsidian + reports
#
[CmdletBinding()]
param(
    [switch]$SkipVerify,
    [switch]$OnlyRender
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptRoot

$Python = if (Test-Path '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
Write-Host "[run_pipeline] python = $Python"

function Step([string]$Name, [string]$Script) {
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Python "system\tools\$Script"
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}

if (-not $OnlyRender) {
    Step 'restructure attachments'  'restructure_attachments.py'
    Step 'extract contracts'        'extract_contract.py'
    Step 'build corpus (sqlite)'    'build_corpus.py'
    Step 'seed parties'             'seed_parties.py'
    Step 'build threads'            'build_threads.py'
    Step 'classify scope'           'classify_scope.py'
    Step 'diff contracts'           'diff_contracts.py'
}

Step 'render obsidian'         'render_obsidian.py'
Step 'render current-state'    'render_current_state.py'

if (-not $SkipVerify) {
    Step 'verify (re-hash all)' 'verify_corpus.py'
}

Write-Host "`n[run_pipeline] done." -ForegroundColor Green
