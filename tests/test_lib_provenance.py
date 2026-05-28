"""Tests for lib_provenance: hashing + slugifier + chain-of-custody append."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from lib_provenance import safe_slug, sha256_file, utcnow_iso


class TestSha256File:
    def test_empty_file_known_hash(self, tmp_path: Path):
        f = tmp_path / "empty"
        f.write_bytes(b"")
        # SHA256 of empty input
        assert sha256_file(f) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_short_string_matches_stdlib(self, tmp_path: Path):
        f = tmp_path / "hi.txt"
        f.write_bytes(b"hello world")
        assert sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()

    def test_streaming_chunks_match_one_shot(self, tmp_path: Path):
        # File larger than the default 1MB chunk so we exercise the loop.
        payload = (b"abc" * 500_000)  # ~1.5 MB
        f = tmp_path / "big"
        f.write_bytes(payload)
        assert sha256_file(f) == hashlib.sha256(payload).hexdigest()


class TestSafeSlug:
    @pytest.mark.parametrize("raw,expected", [
        ("Hello World",                     "hello-world"),
        ("Re: Budget Hearing -- v3",        "re-budget-hearing-v3"),
        ("",                                "untitled"),
        ("///---___",                       "untitled"),
        ("UPPERCASE",                       "uppercase"),
        ("emoji ✨ sparkle",            "emoji-sparkle"),
        ("a/b/c.d_e f",                     "a-b-c-d-e-f"),
    ])
    def test_known_inputs(self, raw: str, expected: str):
        assert safe_slug(raw) == expected

    def test_maxlen_truncates_and_trims_trailing_dash(self):
        s = safe_slug("aaaaaaaaaaaaaaaaaaaa - bbbbbbbbbbb", maxlen=20)
        assert len(s) <= 20
        assert not s.endswith("-")

    def test_collapses_consecutive_separators(self):
        # Multiple separator chars in a row should produce a single dash.
        assert safe_slug("a   b___c---d") == "a-b-c-d"


class TestUtcnowIso:
    def test_format_is_iso8601_zulu(self):
        s = utcnow_iso()
        # YYYY-MM-DDTHH:MM:SSZ
        assert len(s) == 20
        assert s[4] == "-" and s[7] == "-" and s[10] == "T"
        assert s[13] == ":" and s[16] == ":"
        assert s.endswith("Z")
