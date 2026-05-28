"""Tests for the local_mbox capture provider.

These pin behavior at the provider boundary: same interface as
yahoo_browser / gmail_imap (enumerate / fetch_raw_eml / close), no live mail,
two input modes (single .mbox file OR a directory of .eml), and robust
skip-with-warning for corrupt entries so a bad message in a real archive
doesn't poison a multi-thousand-message run.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from providers import get_provider
from providers.local_mbox import (
    LocalMboxProvider,
    _looks_like_valid_message,
    _query_matches,
)

FIXTURES = Path(__file__).parent / "fixtures" / "local_mbox"


def _config_mbox(path: Path) -> dict:
    return {"capture": {"provider": "local_mbox", "mbox_path": str(path)}}


def _config_eml_dir(path: Path) -> dict:
    return {"capture": {"provider": "local_mbox", "eml_dir": str(path)}}


class TestEmptyMbox:
    def test_empty_mbox_yields_nothing(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "empty.mbox"))
        try:
            assert list(p.enumerate([""])) == []
        finally:
            p.close()

    def test_empty_mbox_does_not_crash(self):
        # Just initializing against a 0-byte mbox must not raise.
        p = LocalMboxProvider(_config_mbox(FIXTURES / "empty.mbox"))
        p.close()


class TestSingleMessage:
    def test_yields_exactly_one(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "single.mbox"))
        try:
            results = list(p.enumerate([""]))
            assert len(results) == 1
        finally:
            p.close()

    def test_fetched_raw_contains_expected_headers(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "single.mbox"))
        try:
            msg_id, q = next(iter(p.enumerate([""])))
            raw = p.fetch_raw_eml(msg_id, q)
            assert "Subject: Fixture: Halverton RFP-2025-014" in raw
            assert "alpha.tip@protonmail.example" in raw
        finally:
            p.close()

    def test_msg_id_is_namespaced(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "single.mbox"))
        try:
            msg_id, _ = next(iter(p.enumerate([""])))
            # The provider namespaces mbox ids as mbox:<key>:<sha-prefix>.
            assert msg_id.startswith("mbox:")
        finally:
            p.close()


class TestMultiMessage:
    def test_yields_three(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "multi.mbox"))
        try:
            assert len(list(p.enumerate([""]))) == 3
        finally:
            p.close()

    def test_dedup_across_overlapping_queries(self):
        # If a message matches both queries it must be yielded once, not twice.
        p = LocalMboxProvider(_config_mbox(FIXTURES / "multi.mbox"))
        try:
            results = list(p.enumerate(["Fixture", "RFP-2025-014"]))
            ids = [m for m, _ in results]
            assert len(ids) == len(set(ids))
            # The first query matches all 3; the second query is then a no-op.
            assert len(ids) == 3
        finally:
            p.close()


class TestQueryFiltering:
    @pytest.fixture
    def provider(self):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "multi.mbox"))
        yield p
        p.close()

    def test_from_prefix(self, provider):
        results = list(provider.enumerate(["from:alpha.tip"]))
        assert len(results) == 1
        raw = provider.fetch_raw_eml(*results[0])
        assert "alpha.tip@protonmail.example" in raw

    def test_to_prefix_includes_cc(self, provider):
        # The third message has editor@example-news.com in Cc.
        results = list(provider.enumerate(["to:editor@example-news.com"]))
        assert len(results) == 1
        raw = provider.fetch_raw_eml(*results[0])
        assert "Cc: editor@example-news.com" in raw

    def test_subject_prefix(self, provider):
        results = list(provider.enumerate(["subject:Background"]))
        assert len(results) == 1
        raw = provider.fetch_raw_eml(*results[0])
        assert "Subject: Fixture: Re: Background" in raw

    def test_since_filter(self, provider):
        # since:2026-02-01 -> drops message 1 (Jan 15), keeps messages 2+3.
        results = list(provider.enumerate(["since:2026-02-01"]))
        assert len(results) == 2

    def test_before_filter(self, provider):
        # before:2026-02-01 -> only message 1 (Jan 15).
        results = list(provider.enumerate(["before:2026-02-01"]))
        assert len(results) == 1

    def test_combined_filters_are_anded(self, provider):
        # from:alpha.tip is only message 1; since:2026-02-01 drops it -> empty.
        results = list(provider.enumerate(["from:alpha.tip since:2026-02-01"]))
        assert results == []

    def test_plain_substring(self, provider):
        # All three messages mention 'FICTIONAL FIXTURE' in body.
        results = list(provider.enumerate(["FICTIONAL FIXTURE"]))
        assert len(results) == 3

    def test_empty_query_matches_all(self, provider):
        results = list(provider.enumerate([""]))
        assert len(results) == 3

    def test_no_queries_matches_all(self, provider):
        # Empty queries list: provider yields every message once.
        results = list(provider.enumerate([]))
        assert len(results) == 3


class TestMalformed:
    def test_skips_malformed_and_keeps_good(self, capsys):
        p = LocalMboxProvider(_config_mbox(FIXTURES / "with_malformed.mbox"))
        try:
            results = list(p.enumerate([""]))
            # Exactly one good message survives.
            assert len(results) == 1
            raw = p.fetch_raw_eml(*results[0])
            assert "fixture-malformed-good@example-mail.test" in raw
            # And we did warn about the bad one to stderr.
            captured = capsys.readouterr()
            assert "skipping malformed" in captured.err
        finally:
            p.close()


class TestEmlDir:
    def test_walks_eml_files(self):
        p = LocalMboxProvider(_config_eml_dir(FIXTURES / "eml_dir"))
        try:
            results = list(p.enumerate([""]))
            assert len(results) == 2
            # ids are eml:<relpath> for this mode.
            for msg_id, _ in results:
                assert msg_id.startswith("eml:")
        finally:
            p.close()

    def test_eml_dir_query_filter_still_works(self):
        p = LocalMboxProvider(_config_eml_dir(FIXTURES / "eml_dir"))
        try:
            results = list(p.enumerate(["from:former.cv.eng"]))
            assert len(results) == 1
        finally:
            p.close()


class TestConfigValidation:
    def test_both_keys_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            LocalMboxProvider({"capture": {
                "mbox_path": str(FIXTURES / "single.mbox"),
                "eml_dir":   str(FIXTURES / "eml_dir"),
            }})

    def test_neither_key_raises(self):
        with pytest.raises(ValueError, match="mbox_path"):
            LocalMboxProvider({"capture": {}})

    def test_missing_mbox_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LocalMboxProvider({"capture": {
                "mbox_path": str(tmp_path / "does-not-exist.mbox"),
            }})

    def test_missing_eml_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LocalMboxProvider({"capture": {
                "eml_dir": str(tmp_path / "does-not-exist"),
            }})

    def test_eml_dir_pointing_at_file_raises(self):
        with pytest.raises(NotADirectoryError):
            LocalMboxProvider({"capture": {
                "eml_dir": str(FIXTURES / "single.mbox"),
            }})


class TestRegistry:
    def test_get_provider_local_mbox(self):
        p = get_provider("local_mbox", _config_mbox(FIXTURES / "single.mbox"))
        try:
            assert isinstance(p, LocalMboxProvider)
        finally:
            p.close()

    def test_get_provider_mbox_file_alias(self):
        # 'mbox_file' is the legacy alias the example config originally used.
        p = get_provider("mbox_file", _config_mbox(FIXTURES / "single.mbox"))
        try:
            assert isinstance(p, LocalMboxProvider)
        finally:
            p.close()

    def test_unknown_provider_mentions_local_mbox(self):
        with pytest.raises(ValueError, match="local_mbox"):
            get_provider("does-not-exist", {})


class TestInternals:
    @pytest.mark.parametrize("hdr,expected", [
        ("Message-ID: <abc>\n\nbody", True),
        ("From: alice@example.com\n\nbody", True),
        ("Subject: hi\n\nbody", True),
        ("Date: Wed, 15 Jan 2026 14:22:00 +0000\n\nbody", True),
        ("just some garbage with no headers", False),
    ])
    def test_looks_like_valid_message(self, hdr: str, expected: bool):
        assert _looks_like_valid_message(hdr) is expected

    def test_query_matches_empty(self):
        assert _query_matches("any raw source", "") is True

    def test_query_matches_unknown_prefix_treated_as_plain(self):
        # If a token looks like 'foo:bar' but foo isn't a recognized prefix,
        # the implementation treats the whole token as a plain substring.
        # (Mirrors the gmail_imap parser's posture.)
        raw = "Subject: hello\n\nbody mentions custom:tag inside"
        assert _query_matches(raw, "custom:tag") is True
