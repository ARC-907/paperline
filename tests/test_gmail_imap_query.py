"""Tests for providers.gmail_imap._parse_query -- the kit's portable query
syntax -> IMAP search criteria translator."""
from __future__ import annotations

import pytest
from providers.gmail_imap import _parse_query


class TestPlainTerms:
    def test_single_word_becomes_body_or_subject(self):
        assert _parse_query("renewal") == '(OR BODY "renewal" SUBJECT "renewal")'

    def test_multi_word_joins_with_space(self):
        assert _parse_query("budget hearing") == '(OR BODY "budget hearing" SUBJECT "budget hearing")'

    def test_empty_returns_all(self):
        assert _parse_query("") == "ALL"


class TestPrefixes:
    def test_from_prefix(self):
        assert _parse_query("from:alice@example.com") == 'FROM "alice@example.com"'

    def test_to_prefix(self):
        assert _parse_query("to:bob@example.com") == 'TO "bob@example.com"'

    def test_subject_prefix(self):
        assert _parse_query("subject:important") == 'SUBJECT "important"'

    @pytest.mark.parametrize("token,expected", [
        ("since:2026-01-15", 'SINCE "15-Jan-2026"'),
        ("before:2026-12-31", 'BEFORE "31-Dec-2026"'),
    ])
    def test_date_prefixes_to_imap_format(self, token: str, expected: str):
        assert _parse_query(token) == expected


class TestCombination:
    def test_from_plus_since(self):
        out = _parse_query("from:alice@example.com since:2026-01-01")
        assert 'FROM "alice@example.com"' in out
        assert 'SINCE "01-Jan-2026"' in out

    def test_prefix_plus_plain_term(self):
        # Prefixes parse first; remaining tokens are joined as the body/subject term.
        out = _parse_query("from:alice@example.com renewal")
        assert 'FROM "alice@example.com"' in out
        assert '(OR BODY "renewal" SUBJECT "renewal")' in out

    def test_uppercase_prefix_still_works(self):
        # Prefix matching is case-insensitive.
        assert _parse_query("FROM:alice@example.com") == 'FROM "alice@example.com"'
