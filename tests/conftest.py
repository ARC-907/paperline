"""pytest configuration -- makes the kit's tools importable as plain modules.

The tools under system/tools/ are written as runnable scripts that sys.path-insert
their own directory; for pytest we replicate that on test collection.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "system" / "tools"

# Make `import lib_provenance`, `import config_loader`, `from providers import ...` work.
sys.path.insert(0, str(TOOLS_DIR))
