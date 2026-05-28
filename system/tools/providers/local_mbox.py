"""Local-archive capture provider — reads from .mbox files or directories of .eml.

This is the offline-friendly provider. It does NOT touch a live mail account.
Use it when:

  - You're running the bundled example end-to-end with no Gmail/Yahoo setup
  - You have an exported archive from Apple Mail, Thunderbird, mutt, or
    Gmail Takeout (.mbox)
  - You have a folder full of .eml files exported from any mail client
  - You want to test pipeline changes against a known synthetic corpus

project-config.json `capture` fields used:
  provider:    "local_mbox"  (alias "mbox_file" is also accepted)
  mbox_path:   path to a single .mbox file       \\  exactly ONE of these
  eml_dir:     path to a folder of .eml files    /   must be set
  search_queries: optional list[str]; missing/empty yields all messages
    Each query may use:
      - plain string -- case-insensitive substring of the full RFC822 source
      - prefix `from:address`             -- substring of the From header
      - prefix `to:address`               -- substring of To or Cc headers
      - prefix `subject:keyword`          -- substring of the Subject header
      - prefix `since:YYYY-MM-DD`         -- Date header on/after this UTC date
      - prefix `before:YYYY-MM-DD`        -- Date header before this UTC date

Filters are AND-combined within one query; queries are OR-combined.

Malformed messages are skipped with a warning to stderr; the provider does not
crash on a single bad entry. mbox_path / eml_dir are resolved relative to the
paperline repo root if not absolute.

Implementation notes:
  - mailbox.mbox is used for .mbox files; we read each key as bytes and decode
    utf-8/replace at the boundary so downstream sees str (mirrors gmail_imap).
  - For .eml dirs, Path.glob('**/*.eml') walks recursively.
  - Message IDs emitted to the orchestrator are namespaced and content-hashed
    so re-running against a different archive can't collide in
    system/.dev-scratch/_captured_ids.json.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import mailbox
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_DATE_RX = re.compile(r"^(since|before):(\d{4})-(\d{2})-(\d{2})$", re.I)
_PREFIX_RX = re.compile(r"^(from|to|subject):(.+)$", re.I)


def _decode_bytes(b: bytes) -> str:
    """Defensive utf-8/replace decode — same posture as gmail_imap."""
    return b.decode("utf-8", errors="replace")


def _looks_like_valid_message(raw: str) -> bool:
    """Heuristic 'is this a usable RFC822 message' check.

    The stdlib email parser is famously permissive — it will happily parse a
    garbage byte sequence into a `Message` object with one weird-looking header.
    For the local_mbox provider we want a corruption signal so we can warn-and-skip
    the bad entry. A message with NO recognized standard header (Message-ID,
    From, Subject, Date) is treated as corrupt; the downstream pipeline could
    not do anything useful with it anyway.
    """
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
    except Exception:
        return False
    return any(msg.get(hdr) for hdr in ("Message-ID", "From", "Subject", "Date"))


def _hash_prefix(b: bytes) -> str:
    """12-char sha256 prefix for content-id namespacing."""
    return hashlib.sha256(b).hexdigest()[:12]


def _resolve_path(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO_ROOT / pp)


def _parse_date_header(raw: str) -> datetime | None:
    """Pull and normalize a Date: header. Returns aware-UTC datetime or None."""
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
    except Exception:
        return None
    hdr = msg.get("Date")
    if not hdr:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(hdr)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _header(raw: str, name: str) -> str:
    """Cheap header extraction without re-parsing the whole message."""
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
    except Exception:
        return ""
    return msg.get(name, "") or ""


def _query_matches(raw: str, query: str) -> bool:
    """Return True iff `raw` matches every token in `query`.

    A token is either a typed prefix (from:/to:/subject:/since:/before:) or a
    plain term that must appear as a case-insensitive substring of the whole
    RFC822 source. An empty query matches every message.
    """
    tokens = query.split()
    if not tokens:
        return True
    raw_lower = raw.lower()
    for tok in tokens:
        m = _DATE_RX.match(tok)
        if m:
            kind, y, mo, d = m.group(1).lower(), int(m.group(2)), int(m.group(3)), int(m.group(4))
            cutoff = datetime(y, mo, d, tzinfo=UTC)
            dt = _parse_date_header(raw)
            if dt is None:
                return False
            if kind == "since" and dt < cutoff:
                return False
            if kind == "before" and dt >= cutoff:
                return False
            continue
        m = _PREFIX_RX.match(tok)
        if m:
            field, needle = m.group(1).lower(), m.group(2).lower()
            if field == "from" and needle not in _header(raw, "From").lower():
                return False
            if field == "to":
                # Match against To OR Cc — semantically closer to "addressed-to".
                combined = (_header(raw, "To") + " " + _header(raw, "Cc")).lower()
                if needle not in combined:
                    return False
            if field == "subject" and needle not in _header(raw, "Subject").lower():
                return False
            continue
        # Plain term: substring on the whole source
        if tok.lower() not in raw_lower:
            return False
    return True


class LocalMboxProvider:
    name = "local_mbox"

    def __init__(self, config: dict):
        cap = config.get("capture", {})
        mbox_path = cap.get("mbox_path")
        eml_dir = cap.get("eml_dir")

        if mbox_path and eml_dir:
            raise ValueError(
                "project-config.json -> capture.{mbox_path, eml_dir}: set exactly one, not both.")
        if not mbox_path and not eml_dir:
            raise ValueError(
                "project-config.json -> capture: local_mbox requires either "
                "'mbox_path' (a .mbox file) or 'eml_dir' (a folder of .eml files).")

        self._messages: dict[str, str] = {}  # msg_id -> raw RFC822 str

        if mbox_path:
            self._load_mbox(_resolve_path(mbox_path))
        else:
            self._load_eml_dir(_resolve_path(eml_dir))

    def _load_mbox(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"local_mbox: mbox_path does not exist: {path}")
        # Empty file is a valid (degenerate) mbox — yield nothing, no crash.
        if path.stat().st_size == 0:
            return
        mb = mailbox.mbox(str(path), create=False)
        try:
            for key in mb.iterkeys():
                try:
                    raw_bytes = mb.get_bytes(key)
                except Exception as e:
                    print(f"[local_mbox] skipping mbox key {key}: {e}", file=sys.stderr)
                    continue
                raw = _decode_bytes(raw_bytes)
                if not _looks_like_valid_message(raw):
                    print(
                        f"[local_mbox] skipping malformed mbox key {key}: "
                        f"no recognized RFC822 headers found",
                        file=sys.stderr,
                    )
                    continue
                msg_id = f"mbox:{key}:{_hash_prefix(raw_bytes)}"
                self._messages[msg_id] = raw
        finally:
            mb.close()

    def _load_eml_dir(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"local_mbox: eml_dir does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"local_mbox: eml_dir is not a directory: {path}")
        for eml_path in sorted(path.glob("**/*.eml")):
            try:
                raw_bytes = eml_path.read_bytes()
            except Exception as e:
                print(f"[local_mbox] skipping unreadable {eml_path}: {e}", file=sys.stderr)
                continue
            raw = _decode_bytes(raw_bytes)
            if not _looks_like_valid_message(raw):
                print(
                    f"[local_mbox] skipping malformed {eml_path}: "
                    f"no recognized RFC822 headers found",
                    file=sys.stderr,
                )
                continue
            rel = eml_path.relative_to(path).as_posix()
            msg_id = f"eml:{rel}"
            self._messages[msg_id] = raw

    def enumerate(self, queries: list[str]) -> Iterator[tuple[str, str]]:
        """Yield (msg_id, query) for each message matching any query.

        If `queries` is empty or contains only an empty string, every message
        is yielded once with an empty query. A message that matches multiple
        queries is yielded exactly once, attributed to the first matching query
        (mirroring the dedup posture of yahoo_browser and gmail_imap).
        """
        effective = queries if queries else [""]
        seen: set[str] = set()
        for q in effective:
            for msg_id, raw in self._messages.items():
                if msg_id in seen:
                    continue
                if _query_matches(raw, q):
                    seen.add(msg_id)
                    yield msg_id, q

    def fetch_raw_eml(self, msg_id: str, query: str) -> str:
        return self._messages.get(msg_id, "")

    def close(self):
        # No held resources; everything was read once at __init__.
        self._messages.clear()
