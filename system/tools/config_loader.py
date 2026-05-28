"""Single source of truth for project-specific configuration.

All tools that have project-specific behavior (contacts, relevance rules,
capture addresses) read from system/project-config.json via this module.
To deploy Paperline for a different project, edit ONLY
system/project-config.json -- no Python source edits needed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import REPO_ROOT  # type: ignore

CONFIG_PATH = REPO_ROOT / "system" / "project-config.json"

_cache: dict | None = None


def load() -> dict:
    """Load + cache the project-config.json. Returns the parsed dict."""
    global _cache
    if _cache is None:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"system/project-config.json not found at {CONFIG_PATH}.\n"
                f"Copy the kit's template and customize for your project.")
        _cache = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _cache


def contacts() -> list[dict]:
    return load().get("contacts", [])


def project_meta() -> dict:
    return load().get("project", {})


def scope_rules_compiled() -> dict[str, list]:
    """Returns relevance rules with regex patterns pre-compiled (case-insensitive)."""
    rules = load().get("scope_rules", {})
    return {
        "in_scope_email": [re.compile(p, re.I) for p in rules.get("in_scope_email_patterns", [])],
        "in_scope_subject": [re.compile(p, re.I) for p in rules.get("in_scope_subject_patterns", [])],
        "attachment_in_scope": [re.compile(p, re.I) for p in rules.get("attachment_in_scope_patterns", [])],
        "off_scope_sender": [re.compile(p, re.I) for p in rules.get("off_scope_sender_patterns", [])],
    }


def report_templates() -> dict:
    return load().get("report_templates", {})


def capture_search_queries() -> list[str]:
    cap = load().get("capture", {})
    # Accept either the new neutral name or the legacy yahoo_-prefixed name.
    return cap.get("search_queries") or cap.get("yahoo_search_queries", [])


def capture_address_whitelist() -> list[str]:
    return load().get("capture", {}).get("in_scope_address_whitelist", [])
