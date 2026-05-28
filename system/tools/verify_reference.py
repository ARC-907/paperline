"""Verify the reference subsystem: every file under reference/doctrine/ hashes
to the value recorded in its .provenance.json sidecar.

Writes a timestamped verification report and appends a REFERENCE-VERIFY event
to the reference COC log. Never touches the evidence COC.

Usage:
  python system/tools/verify_reference.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    REPO_ROOT,
    REPORTS_DIR,
    append_operations_log,
    sha256_file,
    utcnow_iso,
)

CONFIG_PATH = REPO_ROOT / "system" / "reference-config.json"


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def main():
    cfg = _load_config()
    reference_root = REPO_ROOT / cfg["reference"]["reference_root"]
    ops_log_path = REPO_ROOT / cfg["reference"]["ops_log_path"]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    failures: list[dict] = []
    files_checked = 0
    ok_count = 0
    missing_sidecar = 0

    if not reference_root.exists():
        print(f"[warn] reference root not found: {reference_root}")
    else:
        # Walk all of reference/ except _archive/ (matches build_reference.py scope).
        for md_path in sorted(reference_root.rglob("*.md")):
            rel_parts = md_path.relative_to(reference_root).parts
            if rel_parts and rel_parts[0].startswith("_archive"):
                continue
            if md_path.name.lower() == "readme.md":
                continue
            sidecar = md_path.parent / (md_path.name + ".provenance.json")
            files_checked += 1
            if not sidecar.exists():
                missing_sidecar += 1
                failures.append({
                    "file": str(md_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "error": "missing provenance sidecar",
                })
                continue
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception as e:
                failures.append({
                    "file": str(md_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "error": f"unreadable sidecar: {e}",
                })
                continue
            recorded = data.get("artifact_sha256")
            actual = sha256_file(md_path)
            if recorded != actual:
                failures.append({
                    "file": str(md_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "error": "sha256 mismatch",
                    "recorded": recorded,
                    "actual": actual,
                })
            else:
                ok_count += 1

    fail_count = len(failures)
    ts = utcnow_iso().replace(":", "-")
    report = REPORTS_DIR / f"verification-reference-{ts}.md"
    lines = [
        f"# Reference verification — {ts}",
        "",
        f"- Files checked: **{files_checked}**",
        f"- OK: **{ok_count}**",
        f"- Failures: **{fail_count}** (missing sidecars: {missing_sidecar})",
        "",
    ]
    if failures:
        lines.append("## Failures\n")
        for f in failures:
            lines.append(f"- `{f['file']}`: {f['error']}")
            if "recorded" in f:
                lines.append(f"  - recorded: `{f['recorded']}`")
                lines.append(f"  - actual:   `{f['actual']}`")
    else:
        lines.append("All reference artifacts verified.\n")
    report.write_text("\n".join(lines), encoding="utf-8")

    append_operations_log(
        "REFERENCE-VERIFY-OK" if fail_count == 0 else "REFERENCE-VERIFY-FAIL",
        report,
        log_path=ops_log_path,
        notes=f"checked={files_checked} ok={ok_count} fail={fail_count}",
    )
    print(f"OK={ok_count}  FAIL={fail_count}  CHECKED={files_checked}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
