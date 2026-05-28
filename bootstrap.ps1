# bootstrap.ps1 -- One-command setup for a fresh checkout.
#
# What it does, in order:
#   1. Find Python 3.12+ (via py launcher; fallback to `python` on PATH)
#   2. Create .venv via stdlib venv (or virtualenv fallback if stdlib venv is broken)
#   3. Upgrade pip in the venv
#   4. Install runtime + dev dependencies via `pip install -e .[dev]`
#   5. (-WithObsidian)  install Obsidian via winget (Windows only)
#   6. (-WithDatasette) install datasette into the venv for browsable SQLite
#   7. Verify the install by importing key packages
#
# Usage:
#   .\bootstrap.ps1                                # core deps only
#   .\bootstrap.ps1 -WithObsidian -WithDatasette   # everything
#   .\bootstrap.ps1 -PythonVersion 3.13            # force a specific py version
#
[CmdletBinding()]
param(
    [string]$PythonVersion = '3.12',
    [switch]$WithObsidian,
    [switch]$WithDatasette,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptRoot

function Find-Python {
    param([string]$Version)
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $found = & py "-$Version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return $found.Trim() }
    }
    $sysPython = Get-Command python -ErrorAction SilentlyContinue
    if ($sysPython) {
        $ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -and ([version]$ver -ge [version]$Version)) { return $sysPython.Source }
    }
    throw "No Python $Version+ found. Install via 'winget install Python.Python.$Version' then re-run."
}

# --- 1. Find Python ---------------------------------------------------------
Write-Host "`n[1/7] Locating Python $PythonVersion+ ..." -ForegroundColor Cyan
$Python = Find-Python -Version $PythonVersion
$Reported = & $Python -c "import sys; print(sys.version.split()[0])"
Write-Host "   found: $Python (Python $Reported)"

# --- 2. Create venv ---------------------------------------------------------
Write-Host "`n[2/7] Creating .venv ..." -ForegroundColor Cyan
if (Test-Path '.venv') {
    if ($Force) {
        Write-Host "   -Force: removing existing .venv"
        Remove-Item -Recurse -Force .venv
    } else {
        Write-Host "   .venv exists -- skipping (use -Force to recreate)"
    }
}
if (-not (Test-Path '.venv')) {
    & $Python -m venv .venv 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   stdlib venv failed; trying virtualenv ..." -ForegroundColor Yellow
        & $Python -m pip install --quiet virtualenv
        & $Python -m virtualenv .venv
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed both ways" }
    }
}
$VenvPython = Join-Path $ScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) { throw ".venv\Scripts\python.exe not found after venv creation" }

# --- 3. Upgrade pip ---------------------------------------------------------
Write-Host "`n[3/7] Upgrading pip ..." -ForegroundColor Cyan
& $VenvPython -m pip install --quiet --upgrade pip

# --- 4. Install dependencies ------------------------------------------------
Write-Host "`n[4/7] Installing kit dependencies (this can take a minute) ..." -ForegroundColor Cyan
& $VenvPython -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- 5. Optional: Obsidian --------------------------------------------------
if ($WithObsidian) {
    Write-Host "`n[5/7] Installing Obsidian via winget ..." -ForegroundColor Cyan
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host "   winget not found; skipping. Install Obsidian manually: https://obsidian.md/download" -ForegroundColor Yellow
    } else {
        & winget install --id Obsidian.Obsidian --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   winget install failed (already installed? offline?). Continuing." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "`n[5/7] Skipping Obsidian (pass -WithObsidian to install)"
}

# --- 6. Optional: Datasette -------------------------------------------------
if ($WithDatasette) {
    Write-Host "`n[6/7] Installing datasette into venv ..." -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet ".[datasette]"
} else {
    Write-Host "`n[6/7] Skipping datasette (pass -WithDatasette to install)"
}

# --- 7. Verify --------------------------------------------------------------
Write-Host "`n[7/7] Verifying install ..." -ForegroundColor Cyan
& $VenvPython -c "import pymupdf, bs4, dateutil, sqlite_utils, pytest, ruff; import sys; print(f'  python {sys.version.split()[0]} ready'); print('  core+dev deps OK')"

Write-Host "`nDone. Activate the venv with:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\Activate.ps1`n"
Write-Host "Next: edit system\project-config.json then run .\run_pipeline.ps1"
