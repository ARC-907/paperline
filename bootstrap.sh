#!/usr/bin/env bash
# bootstrap.sh -- One-command setup for a fresh checkout (macOS / Linux / WSL).
#
# What it does:
#   1. Find Python 3.12+
#   2. Create .venv via stdlib venv (or virtualenv fallback)
#   3. Upgrade pip
#   4. Install runtime + dev deps via `pip install -e .[dev]`
#   5. (--with-obsidian)  install Obsidian via the platform's package manager
#   6. (--with-datasette) install datasette into the venv
#   7. Verify install
#
# Usage:
#   ./bootstrap.sh
#   ./bootstrap.sh --with-obsidian --with-datasette
#   ./bootstrap.sh --python 3.13 --force
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_VERSION="3.12"
WITH_OBSIDIAN=0
WITH_DATASETTE=0
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --python) PYTHON_VERSION="$2"; shift 2 ;;
        --with-obsidian) WITH_OBSIDIAN=1; shift ;;
        --with-datasette) WITH_DATASETTE=1; shift ;;
        --force) FORCE=1; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

# --- 1. Find Python ---------------------------------------------------------
echo
echo "[1/7] Locating Python $PYTHON_VERSION+ ..."
PYTHON=""
for cand in "python$PYTHON_VERSION" "python3.$(echo "$PYTHON_VERSION" | cut -d. -f2)" python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        req_major=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        req_minor=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        if [ "$major" -gt "$req_major" ] || ([ "$major" -eq "$req_major" ] && [ "$minor" -ge "$req_minor" ]); then
            PYTHON=$(command -v "$cand")
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    echo "No Python $PYTHON_VERSION+ found." >&2
    echo "  macOS:  brew install python@$PYTHON_VERSION" >&2
    echo "  Ubuntu: sudo apt install python$PYTHON_VERSION-venv" >&2
    exit 1
fi
echo "   found: $PYTHON ($("$PYTHON" --version))"

# --- 2. Create venv ---------------------------------------------------------
echo
echo "[2/7] Creating .venv ..."
if [ -d .venv ]; then
    if [ "$FORCE" -eq 1 ]; then
        echo "   --force: removing existing .venv"
        rm -rf .venv
    else
        echo "   .venv exists -- skipping (--force to recreate)"
    fi
fi
if [ ! -d .venv ]; then
    if ! "$PYTHON" -m venv .venv 2>/dev/null; then
        echo "   stdlib venv failed; trying virtualenv ..."
        "$PYTHON" -m pip install --quiet virtualenv
        "$PYTHON" -m virtualenv .venv
    fi
fi
VENV_PYTHON=".venv/bin/python"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON=".venv/Scripts/python.exe"
[ -x "$VENV_PYTHON" ] || { echo ".venv python not found after creation" >&2; exit 1; }

# --- 3. Upgrade pip ---------------------------------------------------------
echo
echo "[3/7] Upgrading pip ..."
"$VENV_PYTHON" -m pip install --quiet --upgrade pip

# --- 4. Install dependencies ------------------------------------------------
echo
echo "[4/7] Installing kit dependencies (this can take a minute) ..."
"$VENV_PYTHON" -m pip install --quiet -e ".[dev]"

# --- 5. Optional: Obsidian --------------------------------------------------
if [ "$WITH_OBSIDIAN" -eq 1 ]; then
    echo
    echo "[5/7] Installing Obsidian ..."
    if command -v brew >/dev/null 2>&1; then
        brew install --cask obsidian || echo "   brew install failed (already installed?). Continuing."
    elif command -v snap >/dev/null 2>&1; then
        sudo snap install obsidian --classic || echo "   snap install failed. Continuing."
    elif command -v flatpak >/dev/null 2>&1; then
        flatpak install -y flathub md.obsidian.Obsidian || echo "   flatpak install failed. Continuing."
    else
        echo "   no supported package manager (brew/snap/flatpak); install manually: https://obsidian.md/download"
    fi
else
    echo
    echo "[5/7] Skipping Obsidian (pass --with-obsidian to install)"
fi

# --- 6. Optional: Datasette -------------------------------------------------
if [ "$WITH_DATASETTE" -eq 1 ]; then
    echo
    echo "[6/7] Installing datasette into venv ..."
    "$VENV_PYTHON" -m pip install --quiet ".[datasette]"
else
    echo
    echo "[6/7] Skipping datasette (pass --with-datasette to install)"
fi

# --- 7. Verify --------------------------------------------------------------
echo
echo "[7/7] Verifying install ..."
"$VENV_PYTHON" -c "import pymupdf, bs4, dateutil, sqlite_utils, pytest, ruff; import sys; print(f'  python {sys.version.split()[0]} ready'); print('  core+dev deps OK')"

echo
echo "Done. Activate the venv with:"
echo "    source .venv/bin/activate"
echo
echo "Next: edit system/project-config.json then run ./run_pipeline.sh"
