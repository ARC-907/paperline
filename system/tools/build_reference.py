"""Build the REFERENCE SQLite database from the ingested reference/ tree.

Walks `reference/doctrine/<library_subdir>/<relpath>.md`, parses YAML
frontmatter + markdown headings, populates `system/reference.sqlite`
(schema in `system/reference-schema.sql`).

The DB is deleted and rebuilt fresh every run (the source-of-truth is the
on-disk markdown + provenance sidecars, not the DB).

Usage:
  python system/tools/build_reference.py
  python system/tools/build_reference.py --no-rebuild   # additive update only
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

CONFIG_PATH = REPO_ROOT / "system" / "reference-config.json"
SCHEMA_PATH = REPO_ROOT / "system" / "reference-schema.sql"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


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
        val = val.strip().strip('"').strip("'")
        if val.lower() in ("true", "false"):
            fm[key] = val.lower() == "true"
        elif val.isdigit():
            fm[key] = int(val)
        else:
            fm[key] = val
    return fm, text[m.end():]


def _parse_sections(body: str) -> list[dict]:
    """Split body into sections by markdown headings. Returns ordered list."""
    matches = list(HEADING_RE.finditer(body))
    if not matches:
        return [{
            "section_id": "00.body",
            "heading": "(body)",
            "heading_level": 0,
            "text": body.strip(),
            "char_offset_start": 0,
            "char_offset_end": len(body),
        }]
    sections: list[dict] = []
    # Optional preamble before the first heading.
    if matches[0].start() > 0:
        preamble = body[: matches[0].start()].strip()
        if preamble:
            sections.append({
                "section_id": "00.preamble",
                "heading": "(preamble)",
                "heading_level": 0,
                "text": preamble,
                "char_offset_start": 0,
                "char_offset_end": matches[0].start(),
            })
    used_slugs: dict[str, int] = {}
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[m.end():end].strip()
        # Section ID: ordinal-prefixed kebab slug to keep stable & unique.
        slug_base = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "section"
        n = used_slugs.get(slug_base, 0) + 1
        used_slugs[slug_base] = n
        section_id = f"{i + 1:03d}.{slug_base}" + (f"-{n}" if n > 1 else "")
        sections.append({
            "section_id": section_id,
            "heading": heading,
            "heading_level": level,
            "text": text,
            "char_offset_start": m.start(),
            "char_offset_end": end,
        })
    return sections


def _ingested_at_from_sidecar(path: Path) -> str | None:
    sidecar = path.parent / (path.name + ".provenance.json")
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data.get("retrieval", {}).get("retrieved_at_iso")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-rebuild", action="store_true",
                    help="Additive update only (default: delete + rebuild).")
    args = ap.parse_args()

    cfg = _load_config()
    db_path = REPO_ROOT / cfg["reference"]["db_path"]
    reference_root = REPO_ROOT / cfg["reference"]["reference_root"]
    ops_log_path = REPO_ROOT / cfg["reference"]["ops_log_path"]

    if not args.no_rebuild and db_path.exists():
        db_path.unlink()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    if not reference_root.exists():
        print(f"[warn] reference root not found: {reference_root}")
        print("[warn] DB created empty.")
        conn.commit()
        conn.close()
        return 0

    # Walk all of reference/ EXCEPT _archive/ (the archive holds superseded
    # materials that must remain on disk but stay out of the indexed DB).
    # Skip top-level README.md and any per-subtree READMEs.
    def _eligible(p: Path) -> bool:
        rel_parts = p.relative_to(reference_root).parts
        if rel_parts and rel_parts[0].startswith("_archive"):
            return False
        return p.name.lower() != "readme.md"

    doc_count = 0
    section_count = 0
    for md_path in sorted(reference_root.rglob("*.md")):
        if not _eligible(md_path):
            continue
        rel = md_path.relative_to(REPO_ROOT)
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[warn] read failed: {rel}: {e}")
            continue

        fm, body = _parse_frontmatter(text)
        # library_subdir is the first path component below reference/.
        # (e.g. 'statutes', 'doctrine', 'forms', 'cases')
        rel_to_ref = md_path.relative_to(reference_root)
        library_subdir = rel_to_ref.parts[0] if rel_to_ref.parts else "(unknown)"
        slug = str(rel_to_ref.with_suffix("")).replace("\\", "/")

        cur = conn.execute(
            """INSERT OR REPLACE INTO reference_docs
               (slug, source_path, ingested_path, library_subdir, title, status,
                evidence_tier, category, sha256, size_bytes, body_text, ingested_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                slug,
                str(md_path),
                str(rel).replace("\\", "/"),
                library_subdir,
                fm.get("title") or md_path.stem,
                fm.get("status"),
                fm.get("evidence_tier") if isinstance(fm.get("evidence_tier"), int) else None,
                fm.get("category"),
                sha256_file(md_path),
                md_path.stat().st_size,
                body,
                _ingested_at_from_sidecar(md_path) or utcnow_iso(),
                None,
            ),
        )
        doc_id = cur.lastrowid
        doc_count += 1

        for sec in _parse_sections(body):
            conn.execute(
                """INSERT OR REPLACE INTO reference_sections
                   (doc_id, section_id, heading, heading_level, text,
                    char_offset_start, char_offset_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id,
                    sec["section_id"],
                    sec["heading"],
                    sec["heading_level"],
                    sec["text"],
                    sec["char_offset_start"],
                    sec["char_offset_end"],
                ),
            )
            section_count += 1

    # Mirror the reference operations log into the DB table for queryability.
    if ops_log_path.exists():
        for line in ops_log_path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            ts, ev, art, sha, actor, notes = parts[:6]
            conn.execute(
                """INSERT INTO reference_operations
                   (ts, event_type, artifact_path, sha256, actor, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, ev, art, sha if sha != "-" else None, actor, notes),
            )

    conn.commit()
    conn.close()

    append_operations_log(
        "REFERENCE-BUILD", db_path,
        log_path=ops_log_path,
        sha256=sha256_file(db_path),
        notes=f"docs={doc_count} sections={section_count}",
    )

    print(json.dumps({
        "db_path": str(db_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "docs": doc_count,
        "sections": section_count,
        "rebuilt": not args.no_rebuild,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
