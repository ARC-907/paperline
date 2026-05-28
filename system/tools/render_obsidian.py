"""Generate Obsidian-friendly Markdown notes from the SQLite index.

Outputs (overwriting on each run — safe because they are derived):
  - correspondence/YYYY-MM-DD/README.md       (date dashboard)
  - threads/{thread-slug}.md                  (one per thread)
  - contacts/{contact-slug}.md                (one per party — base + activity)
  - INDEX.md                                  (master timeline + thread + party index)
  - reports/master-timeline.md                (chronological)
  - reports/document-inventory.md             (every artifact)

All links use Obsidian wikilink syntax `[[path/to/note]]`.

Run: `python system/tools/render_obsidian.py`
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import REPO_ROOT, safe_slug, utcnow_iso  # type: ignore

DB_PATH = REPO_ROOT / "system" / "corpus.sqlite"
CORPUS = REPO_ROOT / "correspondence"
THREADS = REPO_ROOT / "threads"
CONTACTS = REPO_ROOT / "contacts"
REPORTS = REPO_ROOT / "reports"


def _open():
    if not DB_PATH.exists():
        print(f"No DB at {DB_PATH}; run build_index.py first.")
        sys.exit(2)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def render_date_dashboards(conn: sqlite3.Connection):
    cur = conn.cursor()
    by_date = defaultdict(list)
    for row in cur.execute("SELECT * FROM messages ORDER BY sent_at"):
        d = (row["sent_at"] or "")[:10]
        if not d:
            continue
        by_date[d].append(row)
    for date_str, msgs in by_date.items():
        out_dir = CORPUS / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "---",
            f"title: {date_str} — date dashboard",
            f"date: {date_str}",
            f"message_count: {len(msgs)}",
            "---",
            "",
            f"# {date_str} — date dashboard",
            "",
            f"_{len(msgs)} messages on this date._",
            "",
            "## Messages",
            "",
        ]
        for m in msgs:
            sub = m["subject"] or "(no subject)"
            frm = m["from_display"] or m["from_email"] or "(unknown)"
            lines.append(f"- `{(m['sent_at'] or '')[11:16]}` **{sub}** — from {frm}")
        lines.append("")
        lines.append("## Attachments")
        lines.append("")
        cur2 = conn.cursor()
        cur2.execute("""SELECT a.* FROM attachments a JOIN messages m ON a.msg_id=m.id WHERE substr(m.sent_at,1,10) = ?""", (date_str,))
        atts = list(cur2.fetchall())
        if not atts:
            lines.append("_(none)_")
        else:
            for a in atts:
                lines.append(f"- `{a['filename_as_sent']}` — sha256 `{(a['sha256'] or '')[:16]}…` — extraction: {a['extraction_status']}")
        lines.append("")
        (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def render_threads(conn: sqlite3.Connection):
    THREADS.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    for t in cur.execute("SELECT * FROM threads"):
        slug = safe_slug(t["subject_canonical"] or t["yahoo_thread_id"] or "thread", maxlen=60)
        lines = [
            "---",
            f"title: Thread — {t['subject_canonical']}",
            f"thread_id: {t['yahoo_thread_id']}",
            f"first: {t['first_msg_at']}",
            f"last: {t['last_msg_at']}",
            f"msg_count: {t['msg_count']}",
            "---",
            "",
            f"# Thread — {t['subject_canonical']}",
            "",
            f"- Yahoo thread id: `{t['yahoo_thread_id']}`",
            f"- First message: {t['first_msg_at']}",
            f"- Last message: {t['last_msg_at']}",
            f"- Messages: {t['msg_count']}",
            "",
            "## Messages",
            "",
        ]
        cur2 = conn.cursor()
        for m in cur2.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY sent_at", (t["id"],)):
            d = (m["sent_at"] or "")[:10]
            sub = m["subject"] or "(no subject)"
            frm = m["from_display"] or m["from_email"] or "(unknown)"
            lines.append(f"- {m['sent_at']} — **{sub}** — from {frm} → [[correspondence/{d}/README]]")
        (THREADS / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")


def render_parties(conn: sqlite3.Connection):
    CONTACTS.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    for p in cur.execute("SELECT * FROM parties"):
        slug = p["slug"]
        lines = [
            "---",
            f"title: {p['display_name']}",
            f"role: {p['role']}",
            "---",
            "",
            f"# {p['display_name']}",
            "",
            f"- Role: {p['role']}",
            f"- Email addresses: {p['email_addresses']}",
            "",
            "## Activity",
            "",
        ]
        emails = json.loads(p["email_addresses"] or "[]")
        if emails:
            placeholders = ",".join("?" for _ in emails)
            cur2 = conn.cursor()
            cur2.execute(f"""SELECT subject, sent_at, direction FROM messages
                             WHERE from_email IN ({placeholders}) OR to_emails LIKE ? ORDER BY sent_at""",
                         (*emails, f"%{emails[0]}%"))
            for m in cur2.fetchall():
                lines.append(f"- {m['sent_at']} — {m['subject']} ({m['direction']})")
        (CONTACTS / f"{slug}.md").write_text("\n".join(lines), encoding="utf-8")


def render_master_index(conn: sqlite3.Connection):
    REPORTS.mkdir(parents=True, exist_ok=True)
    cur = conn.cursor()
    # Detect optional in_scope column
    cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)").fetchall()]
    has_scope = "in_scope" in cols
    lines = [
        "---",
        "title: Master timeline",
        f"generated_at: {utcnow_iso()}",
        "---",
        "",
        "# Master timeline",
        "",
    ]
    if has_scope:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import config_loader  # type: ignore
            heading = config_loader.report_templates().get(
                "obsidian_in_scope_section_heading") or "In-scope"
        except Exception:
            heading = "In-scope"
        lines.append(f"## {heading}\n")
        cur.execute("""
            SELECT m.sent_at, m.subject, m.from_display, m.from_email, m.has_attachments,
                   (SELECT COUNT(*) FROM attachments a WHERE a.msg_id=m.id) AS att_count
            FROM messages m WHERE m.in_scope = 1 ORDER BY m.sent_at
        """)
        for r in cur.fetchall():
            d = (r["sent_at"] or "")[:10]
            flag = f" ({r['att_count']} att)" if r["att_count"] else ""
            lines.append(f"- {r['sent_at']} -- **{r['subject']}** -- from {r['from_display'] or r['from_email']}{flag} -- [[correspondence/{d}/README]]")
        lines.append("\n## Irrelevant (captured but not part of the project timeline)\n")
        cur.execute("""
            SELECT m.sent_at, m.subject, m.from_display, m.from_email,
                   (SELECT COUNT(*) FROM attachments a WHERE a.msg_id=m.id) AS att_count
            FROM messages m WHERE COALESCE(m.in_scope, 0) = 0 ORDER BY m.sent_at
        """)
        for r in cur.fetchall():
            d = (r["sent_at"] or "")[:10]
            flag = f" ({r['att_count']} att)" if r["att_count"] else ""
            lines.append(f"- {r['sent_at']} -- {r['subject']} -- from {r['from_display'] or r['from_email']}{flag}")
    else:
        cur.execute("""
            SELECT m.sent_at, m.subject, m.from_display, m.from_email, m.has_attachments,
                   (SELECT COUNT(*) FROM attachments a WHERE a.msg_id=m.id) AS att_count
            FROM messages m ORDER BY m.sent_at
        """)
        for r in cur.fetchall():
            d = (r["sent_at"] or "")[:10]
            flag = f" ({r['att_count']} att)" if r["att_count"] else ""
            lines.append(f"- {r['sent_at']} -- **{r['subject']}** -- from {r['from_display'] or r['from_email']}{flag} -- [[correspondence/{d}/README]]")
    (REPORTS / "master-timeline.md").write_text("\n".join(lines), encoding="utf-8")

    inv_lines = ["---", "title: Document inventory", f"generated_at: {utcnow_iso()}", "---", "", "# Document inventory", ""]
    cur.execute("""SELECT a.*, m.sent_at, m.from_display, m.subject FROM attachments a JOIN messages m ON a.msg_id=m.id ORDER BY m.sent_at""")
    for a in cur.fetchall():
        inv_lines.append(f"- `{a['original_path']}` — {a['filename_as_sent']} (sha256 `{(a['sha256'] or '')[:16]}…`, {a['size_bytes']} bytes) — sent {a['sent_at']} by {a['from_display']} re: {a['subject']}")
    (REPORTS / "document-inventory.md").write_text("\n".join(inv_lines), encoding="utf-8")


def render_root_index(conn: sqlite3.Connection):
    cur = conn.cursor()
    m = cur.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    a = cur.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
    c = cur.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    d = cur.execute("SELECT COUNT(DISTINCT substr(sent_at,1,10)) FROM messages").fetchone()[0]
    span = cur.execute("SELECT MIN(sent_at), MAX(sent_at) FROM messages").fetchone()
    lines = [
        "---", "title: Master Index", f"generated_at: {utcnow_iso()}", "---", "",
        "# Master Index", "",
        f"- Messages: **{m}**",
        f"- Attachments: **{a}**",
        f"- Contracts: **{c}**",
        f"- Distinct dates: **{d}**",
        f"- Date span: {span[0]} → {span[1]}" if span and span[0] else "",
        "",
        "## Reports", "",
        "- [[reports/master-timeline]]",
        "- [[reports/document-inventory]]",
        "- [[reports/contract-version-map]]",
        "- [[reports/clause-change-comparison]]",
        "- [[reports/duplicate-report]]",
        "- [[reports/unresolved-issues]]",
        "",
        "## Threads", "",
    ]
    cur.execute("SELECT subject_canonical, yahoo_thread_id FROM threads ORDER BY first_msg_at")
    for t in cur.fetchall():
        slug = safe_slug(t["subject_canonical"] or t["yahoo_thread_id"] or "thread", maxlen=60)
        lines.append(f"- [[threads/{slug}]] — {t['subject_canonical']}")
    lines.append("\n## Parties\n")
    cur.execute("SELECT slug, display_name FROM parties ORDER BY slug")
    for p in cur.fetchall():
        lines.append(f"- [[contacts/{p['slug']}]] — {p['display_name']}")
    (REPO_ROOT / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def render_message_transcripts(conn: sqlite3.Connection):
    """Write per-message Markdown transcripts at correspondence/{date}/messages/{slug}.md."""
    import email
    import email.policy
    import re

    cur = conn.cursor()
    cur.execute("""SELECT m.id, m.yahoo_msg_id, m.sent_at, m.from_email, m.from_display,
                          m.to_emails, m.cc_emails, m.subject, m.eml_path, m.body_html_path,
                          m.thread_id
                   FROM messages m ORDER BY m.sent_at""")
    for r in cur.fetchall():
        date_str = (r["sent_at"] or "")[:10]
        if not date_str:
            continue
        msg_dir = CORPUS / date_str / "messages"
        msg_dir.mkdir(parents=True, exist_ok=True)
        hhmm = (r["sent_at"] or "")[11:16].replace(":", "")
        slug = safe_slug(r["subject"] or "no-subject", 50)
        md_path = msg_dir / f"{hhmm}_y{r['yahoo_msg_id']}_{slug}.md"

        # Parse body text from .eml if present
        body_text = ""
        if r["eml_path"]:
            ep = REPO_ROOT / r["eml_path"]
            if ep.exists():
                try:
                    raw = ep.read_text(encoding="utf-8", errors="replace")
                    msg = email.message_from_string(raw, policy=email.policy.default)
                    if msg.is_multipart():
                        for part in msg.walk():
                            ct = (part.get_content_type() or "")
                            if ct == "text/plain":
                                body_text = (part.get_content() or "")
                                break
                        if not body_text:
                            for part in msg.walk():
                                if part.get_content_type() == "text/html":
                                    html = part.get_content() or ""
                                    body_text = re.sub(r"<[^>]+>", "", html)
                                    body_text = re.sub(r"\n{3,}", "\n\n", body_text)
                                    break
                    else:
                        body_text = msg.get_content() or ""
                except Exception as e:
                    body_text = f"(failed to parse body: {e})"

        # Attachments for this message
        cur2 = conn.cursor()
        cur2.execute("""SELECT filename_as_sent, original_path, sha256, size_bytes
                        FROM attachments WHERE msg_id = ? ORDER BY filename_as_sent""", (r["id"],))
        atts = list(cur2.fetchall())

        # Thread wikilink
        thread_link = ""
        if r["thread_id"]:
            cur2.execute("SELECT subject_canonical FROM threads WHERE id = ?", (r["thread_id"],))
            t = cur2.fetchone()
            if t:
                t_slug = safe_slug(t[0] or "thread", 60)
                thread_link = f"[[threads/{t_slug}]]"

        # Unique alias for Obsidian graph view (so all nodes don't show as
        # "transcript"). Pattern: "<date> <HH:MM> <subject>" -- distinctive
        # without renaming the file.
        subj_for_alias = (r['subject'] or '(no subject)')[:80].replace(chr(34), chr(39))
        unique_alias = f"{date_str} {hhmm[:2]}:{hhmm[2:]} {subj_for_alias}"

        # Build the markdown
        lines = [
            "---",
            f"title: \"{(r['subject'] or '(no subject)').replace(chr(34), chr(39))}\"",
            f"aliases: [\"{unique_alias}\"]",
            f"sent_at: {r['sent_at']}",
            f"from: \"{(r['from_display'] or r['from_email'] or '').replace(chr(34), chr(39))}\"",
            f"to: {r['to_emails']}",
            f"cc: {r['cc_emails']}",
            f"yahoo_msg_id: {r['yahoo_msg_id']}",
            f"thread: \"{thread_link}\"",
            f"date_dashboard: \"[[correspondence/{date_str}/README]]\"",
            f"original_eml: \"{r['eml_path']}\"",
            "---",
            "",
            f"# {r['subject'] or '(no subject)'}",
            "",
            f"- **From:** {r['from_display'] or r['from_email']}",
            f"- **To:** {r['to_emails']}",
            f"- **Cc:** {r['cc_emails']}",
            f"- **Sent:** {r['sent_at']}",
            f"- **Thread:** {thread_link or '(unthreaded)'}",
            f"- **Original .eml:** `{r['eml_path']}`",
            "",
        ]
        if atts:
            lines.append("## Attachments")
            lines.append("")
            for att in atts:
                fn, opath, sha, size = att
                lines.append(f"- `{fn}` ({size} bytes, sha256 `{(sha or '')[:16]}...`) -> `{opath}`")
            lines.append("")
        lines.append("## Body (plaintext extract)")
        lines.append("")
        if body_text:
            lines.append("```")
            # Truncate long bodies; full content lives in the .eml
            truncated = body_text[:8000]
            lines.append(truncated)
            if len(body_text) > 8000:
                lines.append(f"\n[truncated; {len(body_text)} chars total -- see original .eml]")
            lines.append("```")
        else:
            lines.append("_(no plaintext body extracted; see original .eml)_")
        md_path.write_text("\n".join(lines), encoding="utf-8")


def _clear_generated_dirs():
    """Delete previously-rendered files so stale notes don't accumulate."""
    import shutil
    for d in (THREADS, CONTACTS):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    if CORPUS.exists():
        for date_dir in CORPUS.iterdir():
            if not date_dir.is_dir() or date_dir.name.startswith("_"):
                continue
            mdir = date_dir / "messages"
            if mdir.exists():
                shutil.rmtree(mdir)


def main():
    conn = _open()
    _clear_generated_dirs()
    render_date_dashboards(conn)
    render_threads(conn)
    render_parties(conn)
    render_message_transcripts(conn)
    render_master_index(conn)
    render_root_index(conn)
    print("Rendered Obsidian notes.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
