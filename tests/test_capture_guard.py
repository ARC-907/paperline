"""Tests for capture_recent_targeted's two-layer guard helpers.

The guard is the structural defense against off-scope mail reaching disk.
These tests pin the behavior so future refactors can't silently weaken it.
"""
from __future__ import annotations

from capture_recent_targeted import date_from_iso, hhmm_from_iso, is_in_scope, parse_eml

SAMPLE_EML = """From: Charlie <charlie@counterparty.example>
To: Project User <user@self.example>
Cc: bob@witness.example
Subject: Re: Renewal v3
Date: Wed, 14 May 2026 14:23:00 -0500
Message-ID: <abc-123@mail.example>

Body text here.
"""


class TestParseEml:
    def test_extracts_subject_from_address_to_list(self):
        p = parse_eml(SAMPLE_EML)
        assert "charlie@counterparty.example" in p["from"]
        assert any("user@self.example" in t for t in p["to"])
        assert any("bob@witness.example" in c for c in p["cc"])
        assert p["subject"] == "Re: Renewal v3"
        assert p["message_id"] == "abc-123@mail.example"

    def test_date_normalized_to_utc_iso(self):
        p = parse_eml(SAMPLE_EML)
        # 14:23 CDT (-0500) -> 19:23Z
        assert p["sent_at_iso"].startswith("2026-05-14T19:23:00")
        assert p["sent_at_iso"].endswith("+00:00")

    def test_no_attachments_flag_false(self):
        p = parse_eml(SAMPLE_EML)
        assert p["has_attachments"] is False


class TestAddressWhitelistGuard:
    def test_from_address_in_whitelist_passes(self):
        p = {"from": "Alice <alice@counterparty.com>", "to": [], "cc": []}
        assert is_in_scope(p, ["@counterparty.com"]) is True

    def test_to_address_in_whitelist_passes(self):
        p = {"from": "x@x.com", "to": ["alice@counterparty.com"], "cc": []}
        assert is_in_scope(p, ["alice@counterparty.com"]) is True

    def test_cc_address_in_whitelist_passes(self):
        p = {"from": "x@x.com", "to": [], "cc": ["alice@counterparty.com"]}
        assert is_in_scope(p, ["@counterparty.com"]) is True

    def test_no_whitelisted_address_drops(self):
        # Critical: if no header carries a whitelisted address, the message
        # MUST be dropped. This is what stops off-scope pollution.
        p = {"from": "spam@elsewhere.com", "to": ["other@elsewhere.com"], "cc": []}
        assert is_in_scope(p, ["@counterparty.com"]) is False

    def test_match_is_case_insensitive(self):
        p = {"from": "Alice <ALICE@Counterparty.COM>", "to": [], "cc": []}
        assert is_in_scope(p, ["@counterparty.com"]) is True

    def test_partial_address_substring_matches(self):
        # Whitelist patterns are substring-matched, so a domain entry catches
        # any user @ that domain.
        p = {"from": "anyone@counterparty.com", "to": [], "cc": []}
        assert is_in_scope(p, ["@counterparty.com"]) is True


class TestPathHelpers:
    def test_hhmm_from_iso(self):
        assert hhmm_from_iso("2026-05-14T19:23:00+00:00") == "1923"

    def test_hhmm_from_iso_empty_default(self):
        assert hhmm_from_iso("") == "0000"
        assert hhmm_from_iso(None) == "0000"  # type: ignore[arg-type]

    def test_date_from_iso(self):
        assert date_from_iso("2026-05-14T19:23:00+00:00") == "2026-05-14"

    def test_date_from_iso_undated(self):
        assert date_from_iso("") == "_undated"
