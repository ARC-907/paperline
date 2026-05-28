"""Gmail capture provider via IMAP.

Setup (one-time, by the user — NOT the agent):
  1. Enable 2-factor auth on the Gmail account
  2. Create an App Password at https://myaccount.google.com/apppasswords
     (label it 'Paperline' or similar)
  3. Set the env var the project-config.json names (default: GMAIL_APP_PASSWORD)
     before running the capture script:
       PowerShell:  $env:GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"
       Bash:        export GMAIL_APP_PASSWORD="abcdefghijklmnop"
     (Spaces in the App Password don't matter; Google strips them.)

project-config.json `capture` fields used:
  provider: "gmail_imap"
  gmail_username: "your.address@gmail.com"
  gmail_app_password_env: "GMAIL_APP_PASSWORD"      (optional; default shown)
  gmail_mailbox: "[Gmail]/All Mail"                 (optional; default shown)
  search_queries: each becomes an IMAP search applied to the mailbox
    Each query may use:
      - plain string -- treated as `BODY "<string>" OR SUBJECT "<string>"`
      - prefix `from:address@example.com` -- IMAP `FROM "address@example.com"`
      - prefix `to:address@example.com`   -- IMAP `TO "address@example.com"`
      - prefix `subject:keyword`          -- IMAP `SUBJECT "keyword"`
      - prefix `since:YYYY-MM-DD`         -- IMAP `SINCE "DD-Mon-YYYY"`
      Multiple prefixes can be combined: `from:x@y.com since:2026-01-01`

The provider returns each matching message UID as the msg_id and the full
RFC822 source via FETCH UID RFC822. UIDs are stable per mailbox.
"""
from __future__ import annotations

import contextlib
import imaplib
import os
import re
from collections.abc import Iterator
from datetime import datetime


def _parse_query(q: str) -> str:
    """Translate the kit's portable query syntax into IMAP search criteria."""
    parts: list[str] = []
    plain_terms: list[str] = []
    for tok in q.split():
        m = re.match(r"^(from|to|subject):(.+)$", tok, re.I)
        if m:
            parts.append(f'{m.group(1).upper()} "{m.group(2)}"')
            continue
        m = re.match(r"^since:(\d{4})-(\d{2})-(\d{2})$", tok, re.I)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            parts.append(f'SINCE "{dt.strftime("%d-%b-%Y")}"')
            continue
        m = re.match(r"^before:(\d{4})-(\d{2})-(\d{2})$", tok, re.I)
        if m:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            parts.append(f'BEFORE "{dt.strftime("%d-%b-%Y")}"')
            continue
        plain_terms.append(tok)
    if plain_terms:
        joined = " ".join(plain_terms)
        # Plain term -> body OR subject
        parts.append(f'(OR BODY "{joined}" SUBJECT "{joined}")')
    return " ".join(parts) if parts else "ALL"


class GmailImapProvider:
    name = "gmail_imap"

    def __init__(self, config: dict):
        cap = config.get("capture", {})
        self.username = cap.get("gmail_username")
        if not self.username:
            raise ValueError("project-config.json -> capture.gmail_username is required for gmail_imap provider.")
        env_var = cap.get("gmail_app_password_env", "GMAIL_APP_PASSWORD")
        self.password = os.environ.get(env_var)
        if not self.password:
            raise RuntimeError(
                f"Gmail App Password env var {env_var!r} is not set. "
                f"Generate one at https://myaccount.google.com/apppasswords and "
                f"export it before running. See providers/gmail_imap.py docstring.")
        self.mailbox = cap.get("gmail_mailbox", "[Gmail]/All Mail")
        self.host = cap.get("gmail_imap_host", "imap.gmail.com")
        self.port = int(cap.get("gmail_imap_port", 993))

        self._conn = imaplib.IMAP4_SSL(self.host, self.port)
        self._conn.login(self.username, self.password.replace(" ", ""))
        typ, _ = self._conn.select(f'"{self.mailbox}"')
        if typ != "OK":
            raise RuntimeError(f"IMAP SELECT failed for mailbox {self.mailbox!r}")

    def enumerate(self, queries: list[str]) -> Iterator[tuple[str, str]]:
        seen: set[str] = set()
        for q in queries:
            criteria = _parse_query(q)
            typ, data = self._conn.uid("search", None, criteria)
            if typ != "OK" or not data or not data[0]:
                continue
            uids = data[0].split()
            for uid_b in uids:
                uid = uid_b.decode()
                if uid in seen:
                    continue
                seen.add(uid)
                yield uid, q

    def fetch_raw_eml(self, msg_id: str, query: str) -> str:
        typ, data = self._conn.uid("fetch", msg_id, "(RFC822)")
        if typ != "OK" or not data:
            return ""
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                payload = item[1]
                if isinstance(payload, (bytes, bytearray)):
                    return payload.decode("utf-8", errors="replace")
        return ""

    def close(self):
        with contextlib.suppress(Exception):
            self._conn.close()
        with contextlib.suppress(Exception):
            self._conn.logout()
