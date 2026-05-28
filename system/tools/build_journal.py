"""Rebuild `system/journal.sqlite` from the on-disk `journal/entries/` tree.

Walks every `journal/entries/<date>/<HHMM>_<slug>.md`, parses YAML frontmatter +
markdown body, populates `journal_entries`. The DB is deleted and rebuilt fresh
every run (the source-of-truth is the on-disk markdown + provenance sidecars,
not the DB).

Useful when:
  - Entries were added manually (not via `journal.py write`)
  - The DB got corrupted or out of sync
  - You want to re-mirror the operations log into the DB table

Usage:
  python system/tools/build_journal.py
  python system/tools/build_journal.py --no-rebuild   # additive update only
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    REPO_ROOT,
    append_operations_log,
    sha256_file,
    utcnow_iso,
)

CONFIG_PATH = REPO_ROOT / "system" / "journal-config.json"
SCHEMA_PATH = REPO_ROOT / "system" / "journal-schema.sql"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Returns (frontmatter dict, body without frontmatter)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # JSON-array values stay as-is
        if val.startswith("[") and val.endswith("]"):
            try:
                fm[key] = json.loads(val)
                continue
            except Exception:
                pass
        val = val.strip('"').strip("'")
        if val.lower() in ("true", "false"):
            fm[key] = val.lower() == "true"
        elif val.isdigit():
            fm[key] = int(val)
        else:
            fm[key] = val
    return fm, text[m.end():]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-rebuild", action="store_true",
                    help="Additive update only (default: delete + rebuild).")
    args = ap.parse_args()

    cfg = _load_config()
    db_path = REPO_ROOT / cfg["journal"]["db_path"]
    entries_root = REPO_ROOT / cfg["journal"]["entries_root"]
    ops_log_path = REPO_ROOT / cfg["journal"]["ops_log_path"]

    if not args.no_rebuild and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    entry_count = 0
    if entries_root.exists():
        for md_path in sorted(entries_root.rglob("*.md")):
            if md_path.name.lower() == "readme.md":
                continue
            try:
                text = md_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"[warn] read failed: {md_path}: {e}")
                continue
            fm, body = _parse_frontmatter(text)
            slug = fm.get("slug")
            if not slug:
                # Derive slug from path
                date_part = md_path.parent.name
                slug = f"{date_part}/{md_path.stem}"
            entered_at = fm.get("entered_at_iso") or utcnow_iso()
            author = fm.get("author") or cfg["journal"].get("author_default", "operator")
            title = fm.get("title") or md_path.stem
            tags = fm.get("tags") if isinstance(fm.get("tags"), list) else []
            rel_ev = fm.get("related_evidence") if isinstance(fm.get("related_evidence"), list) else []
            rel_ref = fm.get("related_reference") if isinstance(fm.get("related_reference"), list) else []
            conn.execute(
                """INSERT OR REPLACE INTO journal_entries
                   (slug, entered_at_iso, author, title, body_text, tags_json,
                    related_evidence_json, related_reference_json, sha256, size_bytes,
                    source_path, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    slug, entered_at, author, title, body.rstrip(),
                    json.dumps(tags), json.dumps(rel_ev), json.dumps(rel_ref),
                    sha256_file(md_path), md_path.stat().st_size,
                    str(md_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    None,
                ),
            )
            entry_count += 1

    # Mirror operations log into the DB table
    if ops_log_path.exists():
        for line in ops_log_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            ts, ev, art, sha, actor, notes = parts[:6]
            conn.execute(
                """INSERT INTO journal_operations
                   (ts, event_type, artifact_path, sha256, actor, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, ev, art, sha if sha != "-" else None, actor, notes),
            )

    conn.commit()
    conn.close()

    append_operations_log(
        "JOURNAL-BUILD", db_path,
        log_path=ops_log_path,
        sha256=sha256_file(db_path),
        notes=f"entries={entry_count}",
    )
    print(json.dumps({
        "db_path": str(db_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "entries": entry_count,
        "rebuilt": not args.no_rebuild,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
