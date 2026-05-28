"""Yahoo Mail capture provider: Playwright/CDP against debug Chrome :9222.

Requires Chrome already running with --remote-debugging-port=9222 and a
Yahoo Mail tab logged in. The tab need not be selected; the provider
finds it. This implementation extracts the Yahoo-specific logic that was
previously inlined in capture_recent_targeted.py.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

CDP_DEFAULT = "http://localhost:9222"

ENUM_JS = r"""() => {
  const subjectDivs = Array.from(document.querySelectorAll('[id^="email-subject-"]'));
  const out = [];
  for (const el of subjectDivs) {
    if (el.id.startsWith('email-subject-snippet-')) continue;
    const id = el.id.replace('email-subject-','');
    out.push(id);
  }
  return out;
}"""


class YahooBrowserProvider:
    name = "yahoo_browser"

    def __init__(self, config: dict):
        cap = config.get("capture", {})
        self.cdp = cap.get("yahoo_cdp_endpoint", CDP_DEFAULT)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp)
        self._ctx, self._page = self._find_yahoo_page()
        self._search_kw_for_id: dict[str, str] = {}

    def _find_yahoo_page(self):
        for ctx in self._browser.contexts:
            for p in ctx.pages:
                if "mail.yahoo.com" in (p.url or ""):
                    return ctx, p
        ctx = self._browser.contexts[0]
        return ctx, ctx.new_page()

    def _goto(self, url: str):
        if self._page.url.split("?")[0].rstrip("/") == url.rstrip("/"):
            with contextlib.suppress(Exception):
                self._page.reload(wait_until="commit", timeout=30000)
            return
        try:
            self._page.goto(url, wait_until="commit", timeout=30000)
        except Exception:
            try:
                self._page.evaluate(f"window.location.href = {url!r}")
                self._page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception as e2:
                raise RuntimeError(f"goto failed: {e2}") from e2

    def _yahoo_url(self, kw: str, msg_id: str | None = None) -> str:
        kw_e = kw.replace(' ', '%20').replace('@', '%40').replace(':', '%3A')
        base = f"https://mail.yahoo.com/n/search/keyword={kw_e}"
        return f"{base}/messages/{msg_id}" if msg_id else base

    def enumerate(self, queries: list[str]) -> Iterator[tuple[str, str]]:
        seen: set[str] = set()
        for kw in queries:
            try:
                self._goto(self._yahoo_url(kw))
                self._page.wait_for_selector('[id^="email-subject-"]', timeout=20000)
            except (PWTimeout, RuntimeError):
                continue
            ids = self._page.evaluate(ENUM_JS)
            for msg_id in ids:
                if msg_id in seen:
                    continue
                seen.add(msg_id)
                self._search_kw_for_id[msg_id] = kw
                yield msg_id, kw

    def fetch_raw_eml(self, msg_id: str, query: str) -> str:
        kw = query or self._search_kw_for_id.get(msg_id, "")
        self._goto(self._yahoo_url(kw, msg_id))
        self._page.wait_for_selector('[data-test-id="message-toolbar-more-menu"]',
                                     timeout=20000)
        self._page.locator('[data-test-id="message-toolbar-more-menu"]').click()
        self._page.wait_for_timeout(400)
        with self._ctx.expect_page(timeout=10000) as new_page_info:
            self._page.get_by_role("menuitem", name="View raw message").click()
        raw_page = new_page_info.value
        try:
            raw_page.wait_for_load_state("domcontentloaded", timeout=20000)
            pre = raw_page.query_selector("pre")
            return pre.inner_text() if pre else ""
        finally:
            with contextlib.suppress(Exception):
                raw_page.close()

    def close(self):
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._pw.stop()
