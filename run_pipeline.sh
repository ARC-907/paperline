#!/usr/bin/env bash
# run_pipeline.sh -- Rebuild the entire derived layer from on-disk evidence.
#
# Order matches system/tools/README.md. Each step is idempotent.
# Skips capture (step 0) -- run that on its own when you want fresh mail.
#
# Usage:
#   ./run_pipeline.sh                  # full rebuild
#   ./run_pipeline.sh --skip-verify    # skip the (slow) re-hash step
#   ./run_pipeline.sh --only-render    # just regenerate Obsidian + reports
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
else
    PYTHON="python"
fi
echo "[run_pipeline] python = $PYTHON"

SKIP_VERIFY=0
ONLY_RENDER=0
for arg in "$@"; do
    case "$arg" in
        --skip-verify) SKIP_VERIFY=1 ;;
        --only-render) ONLY_RENDER=1 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

step() {
    echo
    echo "=== $1 ==="
    "$PYTHON" "system/tools/$2"
}

if [ "$ONLY_RENDER" -eq 0 ]; then
    step 'restructure attachments' restructure_attachments.py
    step 'extract contracts'       extract_contract.py
    step 'build corpus (sqlite)'   build_corpus.py
    step 'seed parties'            seed_parties.py
    step 'build threads'           build_threads.py
    step 'classify scope'          classify_scope.py
    step 'diff contracts'          diff_contracts.py
fi

step 'render obsidian'      render_obsidian.py
step 'render current-state' render_current_state.py

if [ "$SKIP_VERIFY" -eq 0 ]; then
    step 'verify (re-hash all)' verify_corpus.py
fi

echo
echo "[run_pipeline] done."
