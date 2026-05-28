"""Group messages into threads by RFC822 In-Reply-To/References (when available)
and by normalized subject (the fallback that catches most real-world chains).

Populates the threads table and sets messages.thread_id. Idempotent.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import REPO_ROOT  # type: ignore

DB_PATH = REPO_ROOT / "system" / "corpus.sqlite"
ORIG = REPO_ROOT / "correspondence"

REPLY_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd|forwarded)\s*:\s*", re.I)


def normalize_subject(s: str) -> str:
    if not s:
        return ""
    prev = None
    cur = s.strip()
    while prev != cur:
        prev = cur
        cur = REPLY_PREFIX_RE.sub("", cur).strip()
    # collapse whitespace
    cur = re.sub(r"\s+", " ", cur)
    return cur.lower()


def load_headers(headers_json_path: str) -> dict:
    if not headers_json_path:
        return {}
    p = REPO_ROOT / headers_json_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    if not DB_PATH.exists():
        print("No DB.")
        return 1
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Reset threads table + messages.thread_id
    cur.execute("DELETE FROM threads")
    cur.execute("UPDATE messages SET thread_id = NULL")

    # Build a map: rfc822_msg_id -> message id for header-chain matching
    cur.execute("SELECT id, rfc822_msg_id FROM messages WHERE rfc822_msg_id IS NOT NULL AND rfc822_msg_id != ''")
    by_rfc = {r[1].strip("<>"): r[0] for r in cur.fetchall()}

    # Read each message's In-Reply-To / References from headers.json
    parents: dict[int, int | None] = {}
    cur.execute("""SELECT id, headers_json_path, body_html_path, eml_path FROM messages""")
    rows = cur.fetchall()
    # headers_json_path may be empty in our build_index; fall back to eml file path -> .headers.json
    for mid, hj_path, html_path, eml_path in rows:
        candidate_paths = [hj_path]
        for p in (html_path, eml_path):
            if p:
                candidate_paths.append(str(Path(p).with_suffix("")) + ".headers.json")
        hd = {}
        for cp in candidate_paths:
            if cp:
                hd = load_headers(cp)
                if hd:
                    break
        # parse parent reference
        ref = None
        irt = hd.get("in_reply_to") or ""
        if irt:
            ref = irt.strip("<>").strip()
        if not ref:
            refs = hd.get("references") or ""
            if refs:
                # last reference id is the immediate parent
                tokens = [t.strip("<>") for t in re.findall(r"<([^>]+)>", refs)]
                if tokens:
                    ref = tokens[-1]
        parent_id = by_rfc.get(ref) if ref else None
        parents[mid] = parent_id

    # Union-find to group messages connected by parent edges
    parent_uf: dict[int, int] = {mid: mid for mid in parents}

    def find(x):
        while parent_uf[x] != x:
            parent_uf[x] = parent_uf[parent_uf[x]]
            x = parent_uf[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent_uf[ra] = rb

    for mid, pid in parents.items():
        if pid is not None and pid in parent_uf:
            union(mid, pid)

    # Also union by normalized subject (catches threads where In-Reply-To is missing)
    cur.execute("SELECT id, subject FROM messages")
    by_subject: dict[str, list[int]] = {}
    for mid, subj in cur.fetchall():
        ns = normalize_subject(subj or "")
        if ns:
            by_subject.setdefault(ns, []).append(mid)
    for mids in by_subject.values():
        if len(mids) >= 2:
            for i in range(1, len(mids)):
                union(mids[0], mids[i])

    # Build thread groups
    groups: dict[int, list[int]] = {}
    for mid in parent_uf:
        root = find(mid)
        groups.setdefault(root, []).append(mid)

    # Insert threads, set message.thread_id
    cur.execute("SELECT id, sent_at, subject, from_display, from_email FROM messages")
    msg_meta = {r[0]: r for r in cur.fetchall()}
    for _root, mids in groups.items():
        # Determine thread metadata
        members = sorted(mids, key=lambda m: msg_meta[m][1] or "")
        first_meta = msg_meta[members[0]]
        last_meta = msg_meta[members[-1]]
        canonical_subject = normalize_subject(first_meta[2] or "")[:80]
        if not canonical_subject:
            canonical_subject = (first_meta[2] or "(no subject)")[:80]
        # Party slugs in this thread (rough — by from_email)
        from_emails = sorted({(msg_meta[m][4] or "").lower() for m in members})
        cur.execute("""INSERT INTO threads
                       (yahoo_thread_id, subject_canonical, party_slugs, first_msg_at, last_msg_at, msg_count, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (None, canonical_subject or first_meta[2] or "(no subject)",
                     json.dumps(from_emails),
                     first_meta[1], last_meta[1], len(members), None))
        thread_pk = cur.lastrowid
        for m in members:
            cur.execute("UPDATE messages SET thread_id = ? WHERE id = ?", (thread_pk, m))

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM threads")
    n = cur.fetchone()[0]
    cur.execute("SELECT subject_canonical, msg_count FROM threads ORDER BY msg_count DESC, first_msg_at LIMIT 12")
    print(f"threads: {n}")
    for row in cur.fetchall():
        print(f"  ({row[1]}) {row[0]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
