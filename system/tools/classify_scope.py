"""Mark each message in_scope (1) or off_scope (0) using rules from
system/project-config.json scope_rules section.

Decision rules (any relevant match returns 1):
  - sender/recipient email matches a relevant email pattern
  - subject matches a relevant subject pattern
  - any attached filename matches a relevant attachment-name pattern

Irrelevant sender patterns auto-exclude. Default is 0 (irrelevant).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader  # type: ignore
from lib_provenance import REPO_ROOT  # type: ignore

DB_PATH = REPO_ROOT / "system" / "corpus.sqlite"


def is_in_scope(rules: dict, from_email: str, to_emails: str, cc_emails: str,
                subject: str, attachment_filenames: list[str] | None = None) -> int:
    blob = " ".join(filter(None, [from_email or "", to_emails or "", cc_emails or ""]))
    for pat in rules["in_scope_email"]:
        if pat.search(blob):
            return 1
    for fn in (attachment_filenames or []):
        for pat in rules["attachment_in_scope"]:
            if pat.search(fn):
                return 1
    for pat in rules["in_scope_subject"]:
        if pat.search(subject or ""):
            return 1
    for pat in rules["off_scope_sender"]:
        if pat.search(from_email or ""):
            return 0
    return 0


def main():
    if not DB_PATH.exists():
        print(f"No DB at {DB_PATH}; run build_corpus.py first.")
        return 1
    rules = config_loader.scope_rules_compiled()
    if not (rules["in_scope_email"] or rules["in_scope_subject"]):
        print("No scope rules in project-config.json -> 'scope_rules'.")
        return 1
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(messages)").fetchall()]
    if "in_scope" not in cols:
        cur.execute("ALTER TABLE messages ADD COLUMN in_scope INTEGER")
    in_, out_ = 0, 0
    for r in cur.execute("SELECT id, from_email, to_emails, cc_emails, subject FROM messages").fetchall():
        att_filenames = [row[0] for row in cur.execute(
            "SELECT filename_as_sent FROM attachments WHERE msg_id = ?", (r[0],)).fetchall()]
        verdict = is_in_scope(rules, r[1] or "", r[2] or "", r[3] or "", r[4] or "", att_filenames)
        cur.execute("UPDATE messages SET in_scope = ? WHERE id = ?", (verdict, r[0]))
        if verdict:
            in_ += 1
        else:
            out_ += 1
    conn.commit()
    print(f"in_scope = 1: {in_}; in_scope = 0: {out_}  (rules from project-config.json)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
