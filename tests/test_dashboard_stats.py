"""Tests for the v0.2 dashboard additions: load_stats() + /launch-obsidian.

Covers:
  - load_stats() returns built=False + zero counters when corpus.sqlite is absent
  - load_stats() returns >0 counts when given a populated fixture sqlite
  - /launch-obsidian returns 302 with a well-formed obsidian:// Location
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from paperline_ui import app as app_module  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────
def _apply_schema(conn: sqlite3.Connection) -> None:
    schema_sql = (REPO_ROOT / "system" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)


def _seed_corpus(conn: sqlite3.Connection) -> None:
    """Insert two messages, one thread, two attachments, one letter, one contract."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO threads (id, subject_canonical, first_msg_at, last_msg_at, msg_count)
           VALUES (1, 'Project kickoff', '2026-01-10', '2026-01-20', 2)"""
    )
    cur.execute(
        """INSERT INTO messages
           (id, thread_id, sent_at, from_email, to_emails, cc_emails, bcc_emails,
            subject, captured_at, capture_method)
           VALUES (1, 1, '2026-01-10T09:30:00Z', 'alice@example.com',
                   ?, ?, ?, 'Kickoff', '2026-01-10T09:35:00Z', 'imported')""",
        (json.dumps(["bob@example.com"]), json.dumps([]), json.dumps([])),
    )
    cur.execute(
        """INSERT INTO messages
           (id, thread_id, sent_at, from_email, to_emails, cc_emails, bcc_emails,
            subject, captured_at, capture_method)
           VALUES (2, 1, '2026-01-20T14:05:00Z', 'bob@example.com',
                   ?, ?, ?, 'Re: Kickoff', '2026-01-20T14:10:00Z', 'imported')""",
        (
            json.dumps(["alice@example.com", "carol@example.com"]),
            json.dumps([]),
            json.dumps([]),
        ),
    )
    cur.execute(
        """INSERT INTO attachments
           (id, msg_id, filename_as_sent, original_path, sha256, size_bytes,
            extraction_status)
           VALUES (1, 1, 'agenda.pdf', 'correspondence/2026-01-10/x/agenda.pdf',
                   'a' * 64, 1234, 'ok')"""
    )
    cur.execute(
        """INSERT INTO attachments
           (id, msg_id, filename_as_sent, original_path, sha256, size_bytes,
            extraction_status)
           VALUES (2, 2, 'notes.docx', 'correspondence/2026-01-20/y/notes.docx',
                   'b' * 64, 5678, 'ok')"""
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS letters (
             id INTEGER PRIMARY KEY,
             slug TEXT, from_who TEXT, sender TEXT, recipient TEXT,
             sent_at TEXT, external_to_corpus INTEGER,
             delivered_by_message TEXT, letter_path TEXT NOT NULL, notes TEXT)"""
    )
    cur.execute(
        """INSERT INTO letters (slug, from_who, letter_path)
           VALUES ('letter-2026-01-15', 'user', 'memos/from-user/letter-2026-01-15')"""
    )
    cur.execute(
        """INSERT INTO contracts (id, contract_type, version_label, notes)
           VALUES (1, 'vendor-msa', 'v01', 'initial draft')"""
    )
    conn.commit()


@pytest.fixture()
def populated_corpus(tmp_path: Path) -> Path:
    db_path = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        _apply_schema(conn)
        _seed_corpus(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def client(monkeypatch, tmp_path: Path) -> TestClient:
    """A TestClient with PROJECT_ROOT pinned at a clean tmp workspace.

    The home page renders against this empty workspace so the per-test
    fixtures don't leak through. /launch-obsidian still finds a config:
    we write a minimal project-config.json in the tmp workspace.
    """
    (tmp_path / "system").mkdir()
    cfg = {"project": {"name": "Test Project", "user_emails": ["t@example.com"]}}
    (tmp_path / "system" / "project-config.json").write_text(
        json.dumps(cfg), encoding="utf-8"
    )
    monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        app_module, "CONFIG_PATH", tmp_path / "system" / "project-config.json"
    )
    monkeypatch.setattr(
        app_module, "CORPUS_DB_PATH", tmp_path / "system" / "corpus.sqlite"
    )
    monkeypatch.setattr(app_module, "REPORTS_DIR", tmp_path / "reports")
    return TestClient(app_module.app)


# ── load_stats() ───────────────────────────────────────────────────────────
class TestLoadStatsAbsent:
    def test_returns_zeros_when_db_missing(self, tmp_path: Path) -> None:
        stats = app_module.load_stats(tmp_path / "does-not-exist.sqlite")
        assert stats["built"] is False
        assert stats["total_messages"] == 0
        assert stats["total_contacts"] == 0
        assert stats["total_threads"] == 0
        assert stats["total_documents"] == 0
        assert stats["last_build_timestamp"] is None
        assert stats["corpus_db_size_bytes"] == 0
        assert stats["date_range"] == {"min": None, "max": None}


class TestLoadStatsPopulated:
    def test_returns_positive_counts(self, populated_corpus: Path) -> None:
        stats = app_module.load_stats(populated_corpus)
        assert stats["built"] is True
        assert stats["total_messages"] == 2
        # alice + bob + carol = 3 distinct senders/recipients
        assert stats["total_contacts"] == 3
        # one thread referenced by both messages
        assert stats["total_threads"] == 1
        # 2 attachments + 1 letter + 1 contract = 4 documents
        assert stats["total_documents"] == 4
        assert stats["corpus_db_size_bytes"] > 0
        assert stats["last_build_timestamp"] is not None
        assert stats["date_range"]["min"] == "2026-01-10T09:30:00Z"
        assert stats["date_range"]["max"] == "2026-01-20T14:05:00Z"


# ── /launch-obsidian ───────────────────────────────────────────────────────
class TestLaunchObsidian:
    def test_returns_302_with_well_formed_url(self, client: TestClient) -> None:
        resp = client.get("/launch-obsidian", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        parsed = urlparse(location)
        assert parsed.scheme == "obsidian"
        assert parsed.netloc == "open"
        # Query string must encode an absolute path to the workspace root.
        assert parsed.query.startswith("path=")
        decoded_path = unquote(parsed.query[len("path=") :])
        assert Path(decoded_path).is_absolute()

    def test_honors_meta_obsidian_vault_override(
        self, client: TestClient, monkeypatch, tmp_path: Path
    ) -> None:
        custom_vault = tmp_path / "elsewhere"
        custom_vault.mkdir()
        cfg = {
            "project": {"name": "X"},
            "meta": {"obsidian_vault": str(custom_vault)},
        }
        (tmp_path / "system" / "project-config.json").write_text(
            json.dumps(cfg), encoding="utf-8"
        )
        resp = client.get("/launch-obsidian", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        decoded_path = unquote(location.split("path=", 1)[1])
        assert Path(decoded_path) == custom_vault
