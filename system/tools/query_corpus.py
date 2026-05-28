"""Query the EVIDENCE corpus (system/corpus.sqlite + documents/.../contract.fields.json).

Every emitted row is prefixed `[EVIDENCE]` (belt-and-suspenders separation from
the optional reference DB). With `--with-reference`, additionally queries
`system/reference.sqlite` and prefixes those rows `[REFERENCE]`. The two DBs
are opened in SEPARATE connections; nothing JOINs across them.

Subcommands:
  text      Full-text search over messages + document sections
            (e.g. `query_corpus.py text "termination clause"`)

  fields    List filled form-field values across all documents, with
            optional filter by family, version, or context substring
            (e.g. `query_corpus.py fields --family contract-vendor-x
                                          --context "payment terms"`)

  checkboxes  List checkboxes with given state across all documents
            (e.g. `query_corpus.py checkboxes --state checked
                                              --family contract-vendor-x`)

  inspect   Dump a single document's structured fields + checkboxes for
            one version (e.g. `query_corpus.py inspect contract-vendor-x v05_2026-05-14`)

Examples:
  python system/tools/query_corpus.py text "Special Provisions"
  python system/tools/query_corpus.py text "termination" --with-reference
  python system/tools/query_corpus.py checkboxes --state checked --family contract-vendor-x
  python system/tools/query_corpus.py fields --family contract-vendor-x --context "% of total"
  python system/tools/query_corpus.py inspect contract-vendor-x v05_2026-05-14
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import CONTRACTS_DIR, REPO_ROOT  # type: ignore

# Make stdout tolerant of any Unicode character.
_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure is not None:
    with contextlib.suppress(Exception):
        _reconfigure(encoding="utf-8", errors="replace")

CORPUS_DB = REPO_ROOT / "system" / "corpus.sqlite"
REF_DB = REPO_ROOT / "system" / "reference.sqlite"


def _fts_escape(query: str) -> str:
    """Phrase-quote a query for FTS5 to make punctuation-safe."""
    q = query.strip()
    if not q:
        return q
    inner = q.replace('"', '""')
    return f'"{inner}"'


# -----------------------------------------------------------------------------
# text — FTS over messages + contract sections in corpus.sqlite
# -----------------------------------------------------------------------------

def cmd_text(args) -> int:
    if not CORPUS_DB.exists():
        print(f"[fatal] corpus DB not found at {CORPUS_DB}")
        return 2
    conn = sqlite3.connect(CORPUS_DB)
    conn.row_factory = sqlite3.Row
    fts_q = _fts_escape(args.query)

    msg_rows: list[dict] = []
    try:
        cur = conn.execute(
            """SELECT m.id, m.subject, m.from_email, m.sent_at, m.body_text, m.eml_path
               FROM messages_fts
               JOIN messages m ON m.id = messages_fts.rowid
               WHERE messages_fts MATCH ?
               LIMIT ?""",
            (fts_q, args.limit),
        )
        for r in cur.fetchall():
            msg_rows.append({
                "layer": "EVIDENCE", "kind": "message",
                "msg_id": r["id"], "subject": r["subject"], "from_email": r["from_email"],
                "sent_at": r["sent_at"], "eml_path": r["eml_path"],
                "snippet": (r["body_text"] or "")[:300],
            })
    except sqlite3.OperationalError:
        pass

    sec_rows: list[dict] = []
    try:
        cur = conn.execute(
            """SELECT cs.id, cs.section_id, cs.heading, cs.text,
                      c.id AS contract_id, c.contract_type, c.version_label
               FROM contract_sections_fts
               JOIN contract_sections cs ON cs.id = contract_sections_fts.rowid
               JOIN contracts c ON c.id = cs.contract_id
               WHERE contract_sections_fts MATCH ?
               LIMIT ?""",
            (fts_q, args.limit),
        )
        for r in cur.fetchall():
            sec_rows.append({
                "layer": "EVIDENCE", "kind": "contract_section",
                "contract_type": r["contract_type"], "version_label": r["version_label"],
                "section_id": r["section_id"], "heading": r["heading"],
                "snippet": (r["text"] or "")[:300],
            })
    except sqlite3.OperationalError:
        pass
    conn.close()

    ref_rows: list[dict] = []
    if args.with_reference and REF_DB.exists():
        rconn = sqlite3.connect(REF_DB)
        rconn.row_factory = sqlite3.Row
        try:
            cur = rconn.execute(
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
        rconn.close()

    if args.json:
        print(json.dumps({
            "query": args.query,
            "evidence_messages": msg_rows,
            "evidence_contract_sections": sec_rows,
            "reference_sections": ref_rows,
            "counts": {
                "evidence_messages": len(msg_rows),
                "evidence_contract_sections": len(sec_rows),
                "reference": len(ref_rows),
            },
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"# Query: {args.query!r}")
    print(f"# Evidence message hits:  {len(msg_rows)}")
    print(f"# Evidence section hits:  {len(sec_rows)}")
    if args.with_reference:
        print(f"# Reference hits:         {len(ref_rows)}")
    print()
    for r in msg_rows:
        snip = r["snippet"].replace("\n", " ")
        print(f"[EVIDENCE] msg#{r['msg_id']} {r['sent_at']} from={r['from_email']} subj={r['subject']!r}")
        print(f"    {snip}")
        print(f"    @ {r['eml_path']}")
        print()
    for r in sec_rows:
        snip = r["snippet"].replace("\n", " ")
        print(f"[EVIDENCE] contract {r['contract_type']} {r['version_label']} §{r['section_id']} -- {r['heading']}")
        print(f"    {snip}")
        print()
    for r in ref_rows:
        snip = r["snippet"].replace("\n", " ")
        print(f"[REFERENCE] {r['library_subdir']}/{r['doc_slug']} §{r['section_id']} -- {r['heading']}")
        print(f"    {snip}")
        print()
    return 0


# -----------------------------------------------------------------------------
# fields — list form-field fills across contract.fields.json files
# -----------------------------------------------------------------------------

def _walk_fields_json():
    """Yield (family, version, fields_json_dict) for every contract version."""
    for fam in sorted(CONTRACTS_DIR.iterdir()):
        if not fam.is_dir() or fam.name.startswith("."):
            continue
        for v in sorted(fam.iterdir()):
            if not v.is_dir():
                continue
            fjson = v / "contract.fields.json"
            if not fjson.exists():
                continue
            try:
                d = json.loads(fjson.read_text(encoding="utf-8"))
            except Exception:
                continue
            yield fam.name, v.name, d


def cmd_fields(args) -> int:
    hits: list[dict] = []
    for family, version, d in _walk_fields_json():
        if args.family and args.family != family:
            continue
        if args.version and args.version != version:
            continue
        for ff in d.get("form_fields", []):
            ctx = (ff.get("context_line") or "").lower()
            val = (ff.get("value") or "")
            if args.context and args.context.lower() not in ctx and args.context.lower() not in val.lower():
                continue
            if args.value and args.value.lower() not in val.lower():
                continue
            hits.append({
                "layer": "EVIDENCE", "kind": "form_field",
                "family": family, "version": version,
                "page": ff.get("page"), "value": val, "font": ff.get("font"),
                "bbox": ff.get("bbox"), "context_line": ff.get("context_line"),
            })

    if args.json:
        print(json.dumps({"hits": hits, "count": len(hits)}, indent=2, ensure_ascii=False))
        return 0
    print(f"# Form-field query  family={args.family or '*'}  version={args.version or '*'}  "
          f"context={args.context or '*'}  value={args.value or '*'}")
    print(f"# hits: {len(hits)}")
    print()
    for h in hits:
        ctx = (h["context_line"] or "")[:140]
        print(f"[EVIDENCE] {h['family']} / {h['version']} pg{h['page']} value={h['value']!r}")
        print(f"    ctx: {ctx!r}")
        print()
    return 0


# -----------------------------------------------------------------------------
# checkboxes — list checkboxes with given state across contracts
# -----------------------------------------------------------------------------

def cmd_checkboxes(args) -> int:
    hits: list[dict] = []
    for family, version, d in _walk_fields_json():
        if args.family and args.family != family:
            continue
        if args.version and args.version != version:
            continue
        for cb in d.get("checkboxes", []):
            if args.state and cb.get("state") != args.state:
                continue
            if args.context and args.context.lower() not in (cb.get("context_line") or "").lower():
                continue
            hits.append({
                "layer": "EVIDENCE", "kind": "checkbox",
                "family": family, "version": version,
                "page": cb.get("page"), "state": cb.get("state"),
                "detection_method": cb.get("detection_method"),
                "adjacent_fill_value": cb.get("adjacent_fill_value"),
                "bbox": cb.get("bbox"),
                "context_line": cb.get("context_line"),
            })

    if args.json:
        print(json.dumps({"hits": hits, "count": len(hits)}, indent=2, ensure_ascii=False))
        return 0
    print(f"# Checkbox query  family={args.family or '*'}  version={args.version or '*'}  "
          f"state={args.state or '*'}  context={args.context or '*'}")
    print(f"# hits: {len(hits)}")
    print()
    for h in hits:
        ctx = (h["context_line"] or "")[:140]
        meta = (f" via={h['detection_method']}" if h.get("detection_method") else "")
        fill = (f" fill={h['adjacent_fill_value']!r}" if h.get("adjacent_fill_value") else "")
        print(f"[EVIDENCE] {h['family']} / {h['version']} pg{h['page']} state={h['state']}{meta}{fill}")
        print(f"    ctx: {ctx!r}")
        print()
    return 0


# -----------------------------------------------------------------------------
# inspect — dump a single contract version's summary
# -----------------------------------------------------------------------------

def cmd_inspect(args) -> int:
    target = CONTRACTS_DIR / args.family / args.version / "contract.fields.json"
    if not target.exists():
        print(f"[fatal] not found: {target.relative_to(REPO_ROOT)}")
        return 2
    d = json.loads(target.read_text(encoding="utf-8"))
    print(f"[EVIDENCE] {args.family} / {args.version}")
    print(f"  source_pdf:  {d.get('source_pdf')}")
    print(f"  source_sha:  {d.get('source_sha256')}")
    print(f"  extracted:   {d.get('extracted_at_iso')}")
    print(f"  pages:       {d.get('page_count')}  chars: {d.get('char_count')}")
    print(f"  fonts:       {list((d.get('fonts_summary') or {}).keys())}")
    print(f"  form_fields: {len(d.get('form_fields', []))}")
    print(f"  checkboxes:  {json.dumps(d.get('checkboxes_summary', {}), indent=2)}")
    print(f"  signatures:  {len(d.get('signatures', []))}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_text = sub.add_parser("text", help="FTS over messages + contract sections")
    p_text.add_argument("query")
    p_text.add_argument("--with-reference", action="store_true")
    p_text.add_argument("--limit", type=int, default=10)
    p_text.add_argument("--json", action="store_true")
    p_text.set_defaults(func=cmd_text)

    p_fields = sub.add_parser("fields", help="Filter filled form-field values")
    p_fields.add_argument("--family")
    p_fields.add_argument("--version")
    p_fields.add_argument("--context", help="Substring match against context_line or value")
    p_fields.add_argument("--value", help="Substring match against value only")
    p_fields.add_argument("--json", action="store_true")
    p_fields.set_defaults(func=cmd_fields)

    p_cbx = sub.add_parser("checkboxes", help="Filter checkboxes by state / context")
    p_cbx.add_argument("--family")
    p_cbx.add_argument("--version")
    p_cbx.add_argument("--state", choices=["empty", "checked", "x"], help="Filter by state")
    p_cbx.add_argument("--context", help="Substring match against context_line")
    p_cbx.add_argument("--json", action="store_true")
    p_cbx.set_defaults(func=cmd_checkboxes)

    p_ins = sub.add_parser("inspect", help="Summary of a single contract version")
    p_ins.add_argument("family")
    p_ins.add_argument("version")
    p_ins.set_defaults(func=cmd_inspect)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
