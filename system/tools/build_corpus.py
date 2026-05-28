"""Build SQLite corpus from the new layout (correspondence/ + documents/).

Walks each correspondence/{date}/<msg-folder>/manifest.json and each
documents/<family>/<version>/manifest.json + decomposed.json, populates the
SQLite tables (messages, attachments, contracts, contract_sections), then
populates threads via build_threads, seeds parties via seed_parties,
and renders the Obsidian face.

Run: `python system/tools/build_corpus.py`
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    CORRESPONDENCE_DIR,
    DOCUMENTS_DIR,
    REPO_ROOT,
    SYSTEM_DIR,
    sha256_file,
    utcnow_iso,
)

DB_PATH = SYSTEM_DIR / "corpus.sqlite"
SCHEMA_PATH = SYSTEM_DIR / "schema.sql"
AUDIT_LOG_PATH = SYSTEM_DIR / "audit-log.log"


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    conn.row_factory = sqlite3.Row
    return conn


def populate_messages_and_attachments(conn: sqlite3.Connection):
    cur = conn.cursor()
    msg_count = att_count = 0
    if not CORRESPONDENCE_DIR.exists():
        return
    for date_dir in sorted(CORRESPONDENCE_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        for msg_dir in sorted(date_dir.iterdir()):
            if not msg_dir.is_dir() or msg_dir.name == "imports":
                continue
            manifest_path = msg_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            man = _load(manifest_path)
            m = man.get("message", {})
            # rfc822_message_id is the persistent identifier; yahoo_msg_id is
            # not stored in manifest.json after migration -- folder name is the
            # only on-disk anchor for the original Yahoo ID.
            rfc = m.get("rfc822_message_id") or ""
            cur.execute("""
                INSERT INTO messages (
                  yahoo_msg_id, rfc822_msg_id, sent_at, from_email, from_display,
                  to_emails, cc_emails, bcc_emails, subject,
                  body_html_path, headers_json_path, eml_path,
                  has_attachments, captured_at, capture_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                None, rfc.strip("<>"), m.get("sent_at_iso"),
                (m.get("from") or ""), (m.get("from") or ""),
                json.dumps(m.get("to", [])), json.dumps(m.get("cc", [])),
                json.dumps(m.get("bcc", [])), m.get("subject"),
                None,
                str((msg_dir / "headers.json").relative_to(REPO_ROOT)).replace("\\", "/"),
                str((msg_dir / "original.eml").relative_to(REPO_ROOT)).replace("\\", "/"),
                int(bool(m.get("has_attachments"))),
                man.get("migrated_at") or man.get("ingested_at") or utcnow_iso(),
                man.get("captured_via", "browser-automation"),
            ))
            msg_id = cur.lastrowid
            msg_count += 1
            # Walk attachments under msg_dir/attachments/
            att_dir = msg_dir / "attachments"
            if att_dir.exists():
                BINARY_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
                               ".png", ".jpg", ".jpeg", ".eml", ".html", ".htm", ".zip"}
                # Two passes: real binaries, then pointer markdowns
                for f in sorted(att_dir.iterdir()):
                    if not f.is_file():
                        continue
                    ext = f.suffix.lower()
                    if ext in BINARY_EXTS:
                        stem = f.stem
                        txt = att_dir / f"{stem}.txt"
                        file_meta = man.get("files", {}).get(f"attachments/{f.name}", {})
                        cur.execute("""INSERT INTO attachments
                                       (msg_id, filename_as_sent, original_path, sha256, size_bytes,
                                        extracted_text_path, extraction_status)
                                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                    (msg_id, f.name,
                                     str(f.relative_to(REPO_ROOT)).replace("\\", "/"),
                                     file_meta.get("sha256") or sha256_file(f),
                                     file_meta.get("size_bytes") or f.stat().st_size,
                                     (str(txt.relative_to(REPO_ROOT)).replace("\\", "/")
                                      if txt.exists() else None),
                                     "ok" if txt.exists() else "pending"))
                        att_count += 1
                    elif f.name.endswith(".pointer.md"):
                        # Parse frontmatter
                        try:
                            txt = f.read_text(encoding="utf-8")
                        except Exception:
                            continue
                        front = {}
                        if txt.startswith("---"):
                            end = txt.find("\n---", 3)
                            if end > 0:
                                for line in txt[4:end].splitlines():
                                    if ":" in line:
                                        k, v = line.split(":", 1)
                                        front[k.strip()] = v.strip()
                        # Determine canonical path + extracted_text_path
                        target = front.get("target_path") or front.get("letter_path") \
                                 or (f"documents/{front.get('contract_family')}/{front.get('contract_version')}"
                                     if front.get("contract_family") else None)
                        if not target:
                            continue
                        # Locate the canonical text mirror
                        canonical_dir = REPO_ROOT / target
                        text_candidate = None
                        if (canonical_dir / "contract.txt").exists():
                            text_candidate = canonical_dir / "contract.txt"
                        elif (canonical_dir / "letter.txt").exists():
                            text_candidate = canonical_dir / "letter.txt"
                        original_filename = front.get("original_filename_as_sent") \
                                            or front.get("original_filename_as_attached") \
                                            or f.name.replace(".pointer.md", "")
                        # Determine size: prefer pointer frontmatter, fall back to canonical file
                        size_bytes = None
                        if front.get("size_bytes"):
                            try:
                                size_bytes = int(front["size_bytes"])
                            except ValueError:
                                size_bytes = None
                        if size_bytes is None:
                            canonical_pdf = canonical_dir / "contract.pdf"
                            canonical_letter = next(canonical_dir.glob("letter.*"), None) \
                                               if canonical_dir.exists() else None
                            for cand in (canonical_pdf, canonical_letter):
                                if cand and cand.exists() and not cand.name.endswith(".txt") \
                                   and not cand.name.endswith(".md") and not cand.name.endswith(".json"):
                                    size_bytes = cand.stat().st_size
                                    break
                        size_bytes = size_bytes or 0
                        try:
                            cur.execute("""INSERT INTO attachments
                                           (msg_id, filename_as_sent, original_path, sha256,
                                            size_bytes, extracted_text_path, extraction_status,
                                            mime_type)
                                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                        (msg_id, original_filename, target,
                                         front.get("sha256") or "unknown", size_bytes,
                                         (str(text_candidate.relative_to(REPO_ROOT)).replace("\\", "/")
                                          if text_candidate else None),
                                         "ok" if text_candidate else "pending",
                                         front.get("type", "pointer")))
                            att_count += 1
                        except Exception as e:
                            print(f"  [warn] pointer insert failed for {f.name}: {e}")
    conn.commit()
    print(f"  messages: {msg_count}, attachments: {att_count}")


def populate_letters(conn: sqlite3.Connection):
    """Walk memos/<who>/<slug>/manifest.json and populate a letters table."""
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS letters (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE,
        from_who TEXT NOT NULL,             -- 'user' | 'other-party'
        sender TEXT,
        recipient TEXT,
        sent_at TEXT,
        external_to_corpus INTEGER,
        delivered_by_message TEXT,           -- relative path to source message dir, or NULL
        letter_path TEXT NOT NULL,           -- relative path to canonical letter folder
        notes TEXT
    )""")
    cur.execute("DELETE FROM letters")
    memos_dir = REPO_ROOT / "memos"
    if not memos_dir.exists():
        return
    n = 0
    for who_dir in sorted(memos_dir.iterdir()):
        if not who_dir.is_dir() or who_dir.name.startswith("."):
            continue
        for slug_dir in sorted(who_dir.iterdir()):
            if not slug_dir.is_dir():
                continue
            mf = slug_dir / "manifest.json"
            if not mf.exists():
                continue
            d = _load(mf)
            ld = d.get("letter", {})
            cur.execute("""INSERT INTO letters
                (slug, from_who, sender, recipient, sent_at,
                 external_to_corpus, delivered_by_message, letter_path, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (slug_dir.name,
                 who_dir.name.replace("from-", ""),
                 ld.get("sender"), ld.get("recipient"), ld.get("sent_at_iso"),
                 int(bool(ld.get("external_to_yahoo_corpus") or ld.get("external_to_corpus") or ld.get("external_to_user_corpus"))),
                 ld.get("delivered_by_message"),
                 str(slug_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
                 ld.get("note")))
            n += 1
    conn.commit()
    print(f"  letters: {n}")


def populate_external_submissions(conn: sqlite3.Connection):
    """Walk filings/<agency>/<slug>/manifest.json and populate."""
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS external_submissions (
        id INTEGER PRIMARY KEY,
        agency TEXT NOT NULL,
        slug TEXT NOT NULL,
        against TEXT,
        filed_on TEXT,
        complaint_id TEXT,
        status TEXT,
        submission_path TEXT NOT NULL,
        UNIQUE(agency, slug)
    )""")
    cur.execute("DELETE FROM external_submissions")
    ext_dir = REPO_ROOT / "filings"
    if not ext_dir.exists():
        return
    n = 0
    for agency_dir in sorted(ext_dir.iterdir()):
        if not agency_dir.is_dir():
            continue
        for slug_dir in sorted(agency_dir.iterdir()):
            if not slug_dir.is_dir():
                continue
            mf = slug_dir / "manifest.json"
            if not mf.exists():
                continue
            d = _load(mf)
            sub = d.get("submission", {})
            cur.execute("""INSERT INTO external_submissions
                (agency, slug, against, filed_on, complaint_id, status, submission_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sub.get("agency", agency_dir.name), slug_dir.name,
                 sub.get("against"), sub.get("filed_on"),
                 sub.get("complaint_id"), sub.get("status"),
                 str(slug_dir.relative_to(REPO_ROOT)).replace("\\", "/")))
            n += 1
    conn.commit()
    print(f"  external_submissions: {n}")


def populate_contracts(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("DELETE FROM contract_sections")
    cur.execute("DELETE FROM contracts")
    n_c = n_s = 0
    if not DOCUMENTS_DIR.exists():
        return
    for family_dir in sorted(DOCUMENTS_DIR.iterdir()):
        if not family_dir.is_dir() or family_dir.name.startswith("."):
            continue
        family = family_dir.name
        for v_dir in sorted(family_dir.iterdir()):
            if not v_dir.is_dir():
                continue
            man = _load(v_dir / "manifest.json")
            decomposed = v_dir / "decomposed.json"
            v_label = v_dir.name
            # Skip empty version folders that have neither manifest nor any
            # contract content
            has_content = (decomposed.exists()
                           or (v_dir / "contract.pdf").exists()
                           or (v_dir / "contract.md").exists()
                           or (v_dir / "contract.txt").exists()
                           or man)
            if not has_content:
                continue
            attachment_id = None
            sourced_from = man.get("sourced_from")
            if sourced_from:
                cur.execute("SELECT id FROM attachments WHERE original_path = ?",
                            (sourced_from,))
                row = cur.fetchone()
                if row:
                    attachment_id = row[0]
            transcript_only = bool(man.get("transcript_only"))
            notes = man.get("label") or man.get("notes") or (
                "transcript-only (no source PDF in corpus)" if transcript_only else None)
            cur.execute("""INSERT INTO contracts
                           (attachment_id, contract_type, version_label, page_count, notes)
                           VALUES (?, ?, ?, ?, ?)""",
                        (attachment_id, family, v_label, None, notes))
            cid = cur.lastrowid
            n_c += 1
            if decomposed.exists():
                d = _load(decomposed)
                for s in d.get("sections", []):
                    cur.execute("""INSERT OR IGNORE INTO contract_sections
                                   (contract_id, section_id, section_path, heading, text,
                                    char_offset_start, char_offset_end, page_start, page_end)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (cid, s.get("section_id"), s.get("section_path"),
                                 s.get("heading"), s.get("text"),
                                 s.get("char_offset_start"), s.get("char_offset_end"),
                                 s.get("page_start"), s.get("page_end")))
                    n_s += 1
    conn.commit()
    print(f"  contracts: {n_c}, contract_sections: {n_s}")


def replay_chain_of_custody(conn: sqlite3.Connection):
    if not AUDIT_LOG_PATH.exists():
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM chain_of_custody")
    n = 0
    for line in AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 6:
            parts.append("")
        ts, evt, path, sha, actor, notes = parts[:6]
        cur.execute("""INSERT INTO chain_of_custody (ts, event_type, artifact_path, sha256, actor, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""", (ts, evt, path, sha or None, actor, notes))
        n += 1
    conn.commit()
    print(f"  chain_of_custody: {n}")


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = init_db()
    print("[1] schema applied")
    print("[2] messages + attachments:")
    populate_messages_and_attachments(conn)
    print("[3] contracts + sections:")
    populate_contracts(conn)
    print("[4] letters:")
    populate_letters(conn)
    print("[5] external submissions:")
    populate_external_submissions(conn)
    print("[6] chain of custody:")
    replay_chain_of_custody(conn)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
