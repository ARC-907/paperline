"""Tests for classify_scope.is_in_scope -- the regex-driven in/out gate."""
from __future__ import annotations

import re

from classify_scope import is_in_scope


def _rules(*, in_email=(), in_subject=(), in_attachment=(), off_sender=()) -> dict:
    return {
        "in_scope_email":    [re.compile(p, re.I) for p in in_email],
        "in_scope_subject":  [re.compile(p, re.I) for p in in_subject],
        "attachment_in_scope": [re.compile(p, re.I) for p in in_attachment],
        "off_scope_sender":  [re.compile(p, re.I) for p in off_sender],
    }


class TestEmailMatch:
    def test_from_address_matches_pattern(self):
        rules = _rules(in_email=[r"@counterparty\.com"])
        assert is_in_scope(rules, "alice@counterparty.com", "", "", "Status update") == 1

    def test_to_address_matches_pattern(self):
        rules = _rules(in_email=[r"@counterparty\.com"])
        assert is_in_scope(rules, "user@self.com", "rep@counterparty.com", "", "Status") == 1

    def test_cc_address_matches_pattern(self):
        rules = _rules(in_email=[r"@counterparty\.com"])
        assert is_in_scope(rules, "user@self.com", "", "rep@counterparty.com", "Status") == 1


class TestSubjectMatch:
    def test_subject_keyword(self):
        rules = _rules(in_subject=[r"\bbudget hearing\b"])
        assert is_in_scope(rules, "x@x", "", "", "Budget Hearing proposal") == 1

    def test_subject_no_match_returns_zero(self):
        rules = _rules(in_subject=[r"\bbudget hearing\b"])
        assert is_in_scope(rules, "x@x", "", "", "Newsletter") == 0


class TestAttachmentMatch:
    def test_attachment_filename_in_scope(self):
        rules = _rules(in_attachment=[r"budget"])
        verdict = is_in_scope(rules, "x@x", "", "", "no subject", attachment_filenames=["draft-budget.pdf"])
        assert verdict == 1

    def test_attachment_irrelevant_when_no_match(self):
        rules = _rules(in_attachment=[r"budget"])
        verdict = is_in_scope(rules, "x@x", "", "", "no subject", attachment_filenames=["receipt.pdf"])
        assert verdict == 0


class TestPrecedence:
    def test_off_scope_sender_does_not_override_email_match(self):
        # Current implementation: in-scope email match returns 1 BEFORE
        # off-scope sender is checked. This test pins that behavior.
        rules = _rules(in_email=[r"@counterparty\.com"], off_sender=[r"^noreply@"])
        # Even if from is noreply@, an in-scope cc address still wins.
        assert is_in_scope(rules, "noreply@counterparty.com", "", "user@self.com", "x") == 1

    def test_off_scope_sender_blocks_when_no_other_match(self):
        rules = _rules(off_sender=[r"^noreply@"])
        assert is_in_scope(rules, "noreply@anything.com", "", "", "x") == 0


class TestEmptyInputs:
    def test_no_rules_no_match(self):
        rules = _rules()
        assert is_in_scope(rules, "x@x", "", "", "subject") == 0

    def test_none_inputs_safe(self):
        rules = _rules(in_email=[r"@x\.com"])
        assert is_in_scope(rules, "", "", "", "") == 0
