"""Journal CLI -- write / read / list / query your private notes about the records.

The journal is a categorically-distinct layer in paperline (alongside the evidence
corpus). It holds YOUR thinking: observations, hypotheses, open issues, lines of
inquiry, to-self notes. Entries land in `journal/entries/YYYY-MM-DD/HHMM_slug.md`
with YAML frontmatter and are indexed into `system/journal.sqlite` for FTS.

Subcommands:
  write     Append a new entry. --body or --body-file required.
  read      Display a specific entry by slug (full or partial match).
  list      List recent entries (newest first).
  query     FTS search over journal entries; --with-evidence also queries the
            evidence corpus (system/corpus.sqlite) and tags each row by layer.
            --with-reference is forward-compatible -- a no-op unless a reference
            DB is present at system/reference.sqlite.

Examples:
  journal.py write --title "Open question on retention period" --body "Need to verify..."
  journal.py write --title "Source-protection thread" --body-file ./notes.md --tags source-protection,thread:foo
  journal.py write --title "Cross-reference observation" --body "..." \\
        --related-evidence documents/contract-2024/v03_2025-09-12/ \\
        --related-evidence correspondence/2025-09-10/1100_followup/
  journal.py read 2026-05-19/retention
  journal.py list --limit 30
  journal.py query "retention" --with-evidence
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    REPO_ROOT,
    Retrieval,
    Source,
    append_operations_log,
    safe_slug,
    sha256_file,
    write_provenance_for_file,
)

_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure is not None:
    with contextlib.suppress(Exception):
        _reconfigure(encoding="utf-8", errors="replace")

CONFIG_PATH = REPO_ROOT / "system" / "journal-config.json"
SCHEMA_PATH = REPO_ROOT / "system" / "journal-schema.sql"
CORPUS_DB = REPO_ROOT / "system" / "corpus.sqlite"
REF_DB = REPO_ROOT / "system" / "reference.sqlite"


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _fts_escape(query: str) -> str:
    q = query.strip()
    if not q:
        return q
    return '"' + q.replace('"', '""') + '"'


def _ensure_db(cfg: dict) -> sqlite3.Connection:
    db_path = REPO_ROOT / cfg["journal"]["db_path"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


# -----------------------------------------------------------------------------
# write
# -----------------------------------------------------------------------------

def cmd_write(args) -> int:
    cfg = _load_config()
    if not args.body and not args.body_file:
        print("[fatal] one of --body or --body-file is required")
        return 2

    body = args.body or Path(args.body_file).read_text(encoding="utf-8")
    title = args.title.strip()
    author = args.author or cfg["journal"].get("author_default", "operator")

    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H%M")
    entered_at_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    slug_part = safe_slug(title, maxlen=50)
    slug = f"{date_str}/{hhmm}_{slug_part}"

    tags = []
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    related_evidence = []
    if args.related_evidence:
        for item in args.related_evidence:
            related_evidence.append(item)

    related_reference = []
    if args.related_reference:
        for item in args.related_reference:
            related_reference.append(item)

    entries_root = REPO_ROOT / cfg["journal"]["entries_root"]
    entry_dir = entries_root / date_str
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{hhmm}_{slug_part}.md"

    if entry_path.exists() and not args.force:
        print(f"[fatal] {entry_path.relative_to(REPO_ROOT)} already exists; pass --force to overwrite")
        return 3

    frontmatter = [
        "---",
        f"slug: \"{slug}\"",
        f"entered_at_iso: \"{entered_at_iso}\"",
        f"author: \"{author}\"",
        f"title: \"{title}\"",
        f"tags: {json.dumps(tags)}",
        f"related_evidence: {json.dumps(related_evidence)}",
        f"related_reference: {json.dumps(related_reference)}",
        "---",
        "",
    ]
    full = "\n".join(frontmatter) + body.rstrip() + "\n"
    entry_path.write_text(full, encoding="utf-8")

    # Provenance sidecar -- journal entries are user-authored content.
    src_obj = Source(
        system="journal-write",
        subject=title,
        from_=author,
        sent_at_iso=entered_at_iso,
    )
    ret = Retrieval(
        method="operator-authored",
        tool="journal.py write",
        retrieved_at_iso=entered_at_iso,
    )
    write_provenance_for_file(
        entry_path, src_obj, ret,
        notes=f"Journal entry by {author}. Tags: {tags}. Title: {title!r}",
    )

    # Operations log -- journal events go to journal-operations.log, never to
    # the evidence corpus's chain-of-custody.log. The journal is engineering
    # bookkeeping, not part of the record-integrity trail.
    ops_log_path = REPO_ROOT / cfg["journal"]["ops_log_path"]
    append_operations_log(
        "JOURNAL-WRITE", entry_path,
        log_path=ops_log_path,
        actor=author,
        sha256=sha256_file(entry_path),
        notes=f"slug={slug!r} title={title[:60]!r} tags={tags}",
    )

    # Insert into the DB so it's queryable immediately.
    conn = _ensure_db(cfg)
    body_text = body.rstrip()
    conn.execute(
        """INSERT OR REPLACE INTO journal_entries
           (slug, entered_at_iso, author, title, body_text, tags_json,
            related_evidence_json, related_reference_json, sha256, size_bytes,
            source_path, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            slug, entered_at_iso, author, title, body_text,
            json.dumps(tags), json.dumps(related_evidence), json.dumps(related_reference),
            sha256_file(entry_path), entry_path.stat().st_size,
            str(entry_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            None,
        ),
    )
    conn.commit()
    conn.close()

    print(f"[JOURNAL] wrote entry: {slug}")
    print(f"          path: {entry_path.relative_to(REPO_ROOT)}")
    return 0


# -----------------------------------------------------------------------------
# read
# -----------------------------------------------------------------------------

def cmd_read(args) -> int:
    cfg = _load_config()
    conn = _ensure_db(cfg)
    conn.row_factory = sqlite3.Row
    # AND-match every '/'-separated piece of the target against the slug. So
    # `read 2026-05-19/retention` matches a slug like
    # `2026-05-19/2001_retention-followup-...` even though the literal
    # substring `2026-05-19/retention` doesn't appear in the slug.
    pieces = [p for p in re.split(r"[/\\]", args.target) if p.strip()]
    if not pieces:
        pieces = [args.target]
    where = " AND ".join(["slug LIKE ?"] * len(pieces))
    params = [f"%{p}%" for p in pieces]
    cur = conn.execute(
        f"SELECT * FROM journal_entries WHERE {where} ORDER BY entered_at_iso DESC LIMIT 5",
        params,
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"[JOURNAL] no entry matched {args.target!r}")
        return 1
    if len(rows) > 1:
        print(f"[JOURNAL] {len(rows)} entries matched {args.target!r}; showing newest:")
        for r in rows:
            print(f"  - {r['slug']}  ({r['entered_at_iso']})  {r['title']!r}")
        print()
    r = rows[0]
    print(f"=== [JOURNAL] {r['slug']} ===")
    print(f"entered_at: {r['entered_at_iso']}    author: {r['author']}")
    print(f"title:      {r['title']}")
    tags = json.loads(r['tags_json'] or "[]")
    rel_ev = json.loads(r['related_evidence_json'] or "[]")
    rel_ref = json.loads(r['related_reference_json'] or "[]")
    if tags:
        print(f"tags:       {tags}")
    if rel_ev:
        print(f"refs (evidence):  {rel_ev}")
    if rel_ref:
        print(f"refs (reference): {rel_ref}")
    print(f"source:     {r['source_path']}  sha256={r['sha256'][:16]}...")
    print()
    print(r['body_text'])
    return 0


# -----------------------------------------------------------------------------
# list
# -----------------------------------------------------------------------------

def cmd_list(args) -> int:
    cfg = _load_config()
    conn = _ensure_db(cfg)
    conn.row_factory = sqlite3.Row
    sql = "SELECT slug, entered_at_iso, title, tags_json FROM journal_entries"
    params: list = []
    if args.since:
        sql += " WHERE entered_at_iso >= ?"
        params.append(args.since + "T00:00:00Z")
    sql += " ORDER BY entered_at_iso DESC LIMIT ?"
    params.append(args.limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    print(f"# Journal entries (showing up to {args.limit}, newest first)")
    for r in rows:
        tags = json.loads(r['tags_json'] or "[]")
        tags_str = f"  [{','.join(tags)}]" if tags else ""
        print(f"  [JOURNAL] {r['entered_at_iso'][:19]}  {r['slug']:<50}  {r['title']!r}{tags_str}")
    print(f"\n({len(rows)} entries)")
    return 0


# -----------------------------------------------------------------------------
# query
# -----------------------------------------------------------------------------

def cmd_query(args) -> int:
    cfg = _load_config()
    conn = _ensure_db(cfg)
    conn.row_factory = sqlite3.Row
    fts_q = _fts_escape(args.query)
    j_rows: list[dict] = []
    try:
        cur = conn.execute(
            """SELECT je.slug, je.entered_at_iso, je.title, je.author,
                      je.body_text, je.tags_json
               FROM journal_entries_fts
               JOIN journal_entries je ON je.id = journal_entries_fts.rowid
               WHERE journal_entries_fts MATCH ?
               LIMIT ?""",
            (fts_q, args.limit),
        )
        for r in cur.fetchall():
            j_rows.append({
                "layer": "JOURNAL",
                "slug": r["slug"], "entered_at": r["entered_at_iso"],
                "title": r["title"], "author": r["author"],
                "tags": json.loads(r["tags_json"] or "[]"),
                "snippet": (r["body_text"] or "")[:300],
            })
    except sqlite3.OperationalError:
        pass
    conn.close()

    ev_rows: list[dict] = []
    if args.with_evidence and CORPUS_DB.exists():
        ec = sqlite3.connect(CORPUS_DB)
        ec.row_factory = sqlite3.Row
        try:
            cur = ec.execute(
                """SELECT m.id, m.subject, m.from_email, m.sent_at, m.body_text, m.eml_path
                   FROM messages_fts
                   JOIN messages m ON m.id = messages_fts.rowid
                   WHERE messages_fts MATCH ?
                   LIMIT ?""",
                (fts_q, args.limit),
            )
            for r in cur.fetchall():
                ev_rows.append({
                    "layer": "EVIDENCE", "kind": "message",
                    "msg_id": r["id"], "subject": r["subject"],
                    "from_email": r["from_email"], "sent_at": r["sent_at"],
                    "snippet": (r["body_text"] or "")[:300], "eml_path": r["eml_path"],
                })
        except sqlite3.OperationalError:
            pass
        try:
            cur = ec.execute(
                """SELECT cs.section_id, cs.heading, cs.text,
                          c.contract_type, c.version_label
                   FROM contract_sections_fts
                   JOIN contract_sections cs ON cs.id = contract_sections_fts.rowid
                   JOIN contracts c ON c.id = cs.contract_id
                   WHERE contract_sections_fts MATCH ?
                   LIMIT ?""",
                (fts_q, args.limit),
            )
            for r in cur.fetchall():
                ev_rows.append({
                    "layer": "EVIDENCE", "kind": "contract_section",
                    "contract_type": r["contract_type"], "version_label": r["version_label"],
                    "section_id": r["section_id"], "heading": r["heading"],
                    "snippet": (r["text"] or "")[:300],
                })
        except sqlite3.OperationalError:
            pass
        ec.close()

    ref_rows: list[dict] = []
    if args.with_reference and REF_DB.exists():
        rc = sqlite3.connect(REF_DB)
        rc.row_factory = sqlite3.Row
        try:
            cur = rc.execute(
                """SELECT rs.section_id, rs.heading, rs.text, rd.slug, rd.library_subdir
                   FROM reference_sections_fts
                   JOIN reference_sections rs ON rs.id = reference_sections_fts.rowid
                   JOIN reference_docs rd ON rd.id = rs.doc_id
                   WHERE reference_sections_fts MATCH ?
                   LIMIT ?""",
                (fts_q, args.limit),
            )
            for r in cur.fetchall():
                ref_rows.append({
                    "layer": "REFERENCE", "kind": "section",
                    "library_subdir": r["library_subdir"], "doc_slug": r["slug"],
                    "section_id": r["section_id"], "heading": r["heading"],
                    "snippet": (r["text"] or "")[:300],
                })
        except sqlite3.OperationalError:
            pass
        rc.close()

    if args.json:
        print(json.dumps({
            "query": args.query,
            "journal": j_rows, "evidence": ev_rows, "reference": ref_rows,
            "counts": {"journal": len(j_rows), "evidence": len(ev_rows), "reference": len(ref_rows)},
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"# Query: {args.query!r}")
    print(f"# Journal hits:    {len(j_rows)}")
    if args.with_evidence:
        print(f"# Evidence hits:   {len(ev_rows)}")
    if args.with_reference:
        print(f"# Reference hits:  {len(ref_rows)}")
    print()
    for r in j_rows:
        snip = r["snippet"].replace("\n", " ")[:280]
        tags = ", ".join(r.get("tags", []))
        tag_str = f"  tags=[{tags}]" if tags else ""
        print(f"[JOURNAL] {r['entered_at'][:19]} {r['slug']:<50} {r['title']!r}{tag_str}")
        print(f"    {snip}")
        print()
    for r in ev_rows:
        snip = r["snippet"].replace("\n", " ")[:280]
        if r.get("kind") == "message":
            print(f"[EVIDENCE] msg {r['sent_at']} from={r['from_email']!r} subj={r['subject']!r}")
        else:
            print(f"[EVIDENCE] {r['contract_type']}/{r['version_label']} §{r['section_id']} -- {r['heading']}")
        print(f"    {snip}")
        print()
    for r in ref_rows:
        snip = r["snippet"].replace("\n", " ")[:280]
        print(f"[REFERENCE] {r['library_subdir']}/{r['doc_slug']} §{r['section_id']} -- {r['heading']}")
        print(f"    {snip}")
        print()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write", help="Write a new journal entry")
    p_write.add_argument("--title", required=True)
    p_write.add_argument("--body", help="Body text (or use --body-file)")
    p_write.add_argument("--body-file", help="Read body from file")
    p_write.add_argument("--author", help="Override default author")
    p_write.add_argument("--tags", help="Comma-separated tags")
    p_write.add_argument("--related-evidence", action="append",
                          help="Pointer into evidence corpus (repeatable)")
    p_write.add_argument("--related-reference", action="append",
                          help="Pointer into reference DB (repeatable; forward-compatible)")
    p_write.add_argument("--force", action="store_true",
                          help="Overwrite an existing entry at the target path")
    p_write.set_defaults(func=cmd_write)

    p_read = sub.add_parser("read", help="Display an entry by slug (or partial match)")
    p_read.add_argument("target", help="Slug or substring to match")
    p_read.set_defaults(func=cmd_read)

    p_list = sub.add_parser("list", help="List recent entries (newest first)")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--since", help="ISO date YYYY-MM-DD lower bound")
    p_list.set_defaults(func=cmd_list)

    p_q = sub.add_parser("query", help="FTS search journal; optionally cross-layer")
    p_q.add_argument("query")
    p_q.add_argument("--with-evidence", action="store_true")
    p_q.add_argument("--with-reference", action="store_true",
                      help="Forward-compatible; no-op unless system/reference.sqlite exists")
    p_q.add_argument("--limit", type=int, default=10)
    p_q.add_argument("--json", action="store_true")
    p_q.set_defaults(func=cmd_query)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
