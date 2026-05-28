"""Verify on-disk content matches recorded SHAs.

Walks every manifest.json (correspondence/{date}/{msg}/manifest.json AND
documents/{family}/{version}/manifest.json) and re-hashes the listed files.
Reports mismatches and missing files. Writes a timestamped report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    CORRESPONDENCE_DIR,
    DOCUMENTS_DIR,
    REPO_ROOT,
    REPORTS_DIR,
    append_audit_log,
    sha256_file,
    utcnow_iso,
)


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    files_checked = 0
    ok_count = 0

    for manifest_path in list(CORRESPONDENCE_DIR.rglob("manifest.json")) + list(DOCUMENTS_DIR.rglob("manifest.json")):
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            failures.append({"manifest": str(manifest_path), "error": f"unreadable: {e}"})
            continue
        files_section = m.get("files", {})
        if not files_section:
            # contracts manifest uses {"contract.pdf": {"sha256": ...}, ...}
            continue
        msg_dir = manifest_path.parent
        for rel, meta in files_section.items():
            recorded_sha = meta.get("sha256") if isinstance(meta, dict) else None
            if not recorded_sha:
                continue
            f = msg_dir / rel
            files_checked += 1
            if not f.exists():
                failures.append({"file": str(f.relative_to(REPO_ROOT)).replace("\\", "/"),
                                 "error": "missing"})
                continue
            actual = sha256_file(f)
            if actual != recorded_sha:
                failures.append({"file": str(f.relative_to(REPO_ROOT)).replace("\\", "/"),
                                 "error": "sha256 mismatch",
                                 "recorded": recorded_sha, "actual": actual})
            else:
                ok_count += 1

    fail_count = len(failures)
    ts = utcnow_iso().replace(":", "-")
    report = REPORTS_DIR / f"verification-{ts}.md"
    lines = [f"# Verification — {ts}", "",
             f"- Files checked: **{files_checked}**",
             f"- OK: **{ok_count}**",
             f"- Failures: **{fail_count}**", ""]
    if failures:
        lines.append("## Failures\n")
        for f in failures:
            lines.append(f"- `{f.get('file') or f.get('manifest')}`: {f['error']}")
            if "recorded" in f:
                lines.append(f"  - recorded: `{f['recorded']}`")
                lines.append(f"  - actual:   `{f['actual']}`")
    else:
        lines.append("All artifacts verified.\n")
    report.write_text("\n".join(lines), encoding="utf-8")

    append_audit_log("VERIFY-OK" if fail_count == 0 else "VERIFY-FAIL",
                            report, notes=f"checked={files_checked} ok={ok_count} fail={fail_count}")
    print(f"OK={ok_count}  FAIL={fail_count}  CHECKED={files_checked}")
    print(f"Report: {report}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
