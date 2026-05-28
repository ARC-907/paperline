"""Query the REFERENCE SQLite DB (system/reference.sqlite).

Every emitted row is prefixed `[REFERENCE]` (belt-and-suspenders separation
from the evidence corpus). With `--with-evidence`, additionally queries
`system/corpus.sqlite` and prefixes those rows `[EVIDENCE]`. The two DBs are
opened in SEPARATE connections; nothing JOINs across them.

Usage:
  python system/tools/query_reference.py "retention period"
  python system/tools/query_reference.py "disclosure requirement" --with-evidence
  python system/tools/query_reference.py "renewal" --limit 5 --json
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import REPO_ROOT  # type: ignore

# Make stdout tolerant of any Unicode character we encounter in snippets,
# even on Windows consoles still defaulting to cp1252.
_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure is not None:
    with contextlib.suppress(Exception):
        _reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = REPO_ROOT / "system" / "reference-config.json"


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _fts_escape(query: str) -> str:
    """Escape a user query for FTS5: phrase-quote non-operator queries to allow
    punctuation like § and dots."""
    q = query.strip()
    if not q:
        return q
    # Wrap in double quotes (FTS5 phrase) to make it punctuation-safe,
    # escaping any embedded double quotes by doubling them.
    inner = q.replace('"', '""')
    return f'"{inner}"'


def _query_reference(db_path: Path, query: str, limit: int) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    fts_q = _fts_escape(query)
    rows: list[dict] = []
    # Section-level hits (most useful).
    try:
        cur = conn.execute(
            """SELECT rs.id, rs.section_id, rs.heading, rs.text,
                      rd.slug, rd.library_subdir, rd.title, rd.ingested_path
               FROM reference_sections_fts
               JOIN reference_sections rs ON rs.id = reference_sections_fts.rowid
               JOIN reference_docs rd ON rd.id = rs.doc_id
               WHERE reference_sections_fts MATCH ?
               LIMIT ?""",
            (fts_q, limit),
        )
        for r in cur.fetchall():
            rows.append({
                "layer": "REFERENCE",
                "kind": "section",
                "library_subdir": r["library_subdir"],
                "doc_slug": r["slug"],
                "doc_title": r["title"],
                "section_id": r["section_id"],
                "heading": r["heading"],
                "ingested_path": r["ingested_path"],
                "snippet": (r["text"] or "")[:300],
            })
    except sqlite3.OperationalError:
        pass

    # If section-level returned nothing, fall back to doc-level.
    if not rows:
        try:
            cur = conn.execute(
                """SELECT rd.id, rd.slug, rd.library_subdir, rd.title,
                          rd.ingested_path, rd.body_text
                   FROM reference_docs_fts
                   JOIN reference_docs rd ON rd.id = reference_docs_fts.rowid
                   WHERE reference_docs_fts MATCH ?
                   LIMIT ?""",
                (fts_q, limit),
            )
            for r in cur.fetchall():
                rows.append({
                    "layer": "REFERENCE",
                    "kind": "doc",
                    "library_subdir": r["library_subdir"],
                    "doc_slug": r["slug"],
                    "doc_title": r["title"],
                    "section_id": None,
                    "heading": None,
                    "ingested_path": r["ingested_path"],
                    "snippet": (r["body_text"] or "")[:300],
                })
        except sqlite3.OperationalError:
            pass

    conn.close()
    return rows


def _query_evidence(db_path: Path, query: str, limit: int) -> list[dict]:
    """Query the evidence corpus on a SEPARATE connection. Never JOIN across.
    Returns [] if corpus.sqlite is absent so the reference side keeps working."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    fts_q = _fts_escape(query)
    rows: list[dict] = []
    try:
        cur = conn.execute(
            """SELECT m.id, m.subject, m.from_email, m.sent_at, m.body_text,
                      m.eml_path
               FROM messages_fts
               JOIN messages m ON m.id = messages_fts.rowid
               WHERE messages_fts MATCH ?
               LIMIT ?""",
            (fts_q, limit),
        )
        for r in cur.fetchall():
            rows.append({
                "layer": "EVIDENCE",
                "kind": "message",
                "msg_id": r["id"],
                "subject": r["subject"],
                "from_email": r["from_email"],
                "sent_at": r["sent_at"],
                "eml_path": r["eml_path"],
                "snippet": (r["body_text"] or "")[:300],
            })
    except sqlite3.OperationalError:
        pass
    conn.close()
    return rows


def _format_row(r: dict) -> str:
    layer = r.get("layer", "?")
    if r.get("kind") == "section":
        head = f"[{layer}] {r['library_subdir']}/{r['doc_slug']} §{r['section_id']} -- {r['heading']}"
        return f"{head}\n    {r['snippet'].replace(chr(10), ' ')}\n    @ {r['ingested_path']}"
    if r.get("kind") == "doc":
        head = f"[{layer}] {r['library_subdir']}/{r['doc_slug']} -- {r['doc_title']}"
        return f"{head}\n    {r['snippet'].replace(chr(10), ' ')}\n    @ {r['ingested_path']}"
    if r.get("kind") == "message":
        head = f"[{layer}] msg#{r['msg_id']} {r['sent_at']} from={r['from_email']} subj={r['subject']!r}"
        return f"{head}\n    {r['snippet'].replace(chr(10), ' ')}\n    @ {r['eml_path']}"
    return f"[{layer}] {r}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", help="Search query (FTS5 phrase).")
    ap.add_argument("--with-evidence", action="store_true",
                    help="Also query corpus.sqlite and prefix those rows [EVIDENCE].")
    ap.add_argument("--limit", type=int, default=10, help="Max rows per layer (default 10).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of formatted text.")
    args = ap.parse_args()

    cfg = _load_config()
    ref_db = REPO_ROOT / cfg["reference"]["db_path"]
    ev_db = REPO_ROOT / "system" / "corpus.sqlite"

    ref_rows = _query_reference(ref_db, args.query, args.limit)
    ev_rows = _query_evidence(ev_db, args.query, args.limit) if args.with_evidence else []

    if args.json:
        print(json.dumps({
            "query": args.query,
            "reference": ref_rows,
            "evidence": ev_rows,
            "counts": {"reference": len(ref_rows), "evidence": len(ev_rows)},
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"# Query: {args.query!r}")
    print(f"# Reference hits: {len(ref_rows)}   Evidence hits: {len(ev_rows) if args.with_evidence else '(not queried)'}")
    print()
    for r in ref_rows:
        print(_format_row(r))
        print()
    if args.with_evidence:
        for r in ev_rows:
            print(_format_row(r))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
