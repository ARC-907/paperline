"""Email-provider abstraction for the capture pipeline.

Each provider implements two operations:

  enumerate(queries: list[str]) -> Iterator[tuple[str, str]]
      Yield (provider_msg_id, query_that_found_it) for each candidate.
      provider_msg_id is opaque to the caller; the provider must accept it
      back in fetch_raw_eml().

  fetch_raw_eml(msg_id: str, query: str) -> str
      Return the full RFC822 source for one message.

  close()
      Release any held resources (browser context, IMAP socket, etc.).

The capture_recent_targeted.py orchestrator picks a provider via
project-config.json -> `capture.provider`. Built-in providers:

  "local_mbox"     -- read from a local .mbox file or directory of .eml files
                      (no live mail account; offline-friendly default)
  "yahoo_browser"  -- Playwright/CDP against Yahoo Mail (debug Chrome :9222)
  "gmail_imap"     -- IMAP via imap.gmail.com (requires App Password env var)

Add new providers by writing a new module in this folder and adding it to
get_provider() below.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class CaptureProvider(Protocol):
    def enumerate(self, queries: list[str]) -> Iterator[tuple[str, str]]: ...
    def fetch_raw_eml(self, msg_id: str, query: str) -> str: ...
    def close(self) -> None: ...


def get_provider(name: str, config: dict) -> CaptureProvider:
    """Instantiate the named provider. config is the full project-config.json
    dict (the provider reads its own section as needed)."""
    if name in ("local_mbox", "mbox_file"):
        # 'mbox_file' is a legacy alias kept so older example configs keep working.
        from . import local_mbox
        return local_mbox.LocalMboxProvider(config)
    if name == "yahoo_browser":
        from . import yahoo_browser
        return yahoo_browser.YahooBrowserProvider(config)
    if name == "gmail_imap":
        from . import gmail_imap
        return gmail_imap.GmailImapProvider(config)
    raise ValueError(f"Unknown capture provider: {name!r}. "
                     f"Built-ins: 'local_mbox', 'yahoo_browser', 'gmail_imap'.")
