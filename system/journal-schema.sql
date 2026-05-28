-- Paperline -- JOURNAL subsystem SQLite schema
-- Categorically separate from corpus.sqlite (the evidence corpus).
-- The journal captures the user's own thinking, observations, hypotheses, and
-- open issues. No shared tables, triggers, FTS namespace, or JOINs with the
-- evidence corpus.
-- SQLite 3.x with FTS5 enabled.
--
-- The optional reference.sqlite layer is independent of the journal --
-- journal queries with --with-reference are a no-op unless a reference DB is
-- present at system/reference.sqlite.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- =========================================================================
-- Journal entries (one row per .md file under journal/entries/)
-- =========================================================================
CREATE TABLE IF NOT EXISTS journal_entries (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,        -- deterministic: YYYY-MM-DD/HHMM_slug
    entered_at_iso  TEXT NOT NULL,               -- ISO 8601 UTC; from frontmatter or filename
    author          TEXT,                        -- from frontmatter; defaults to journal-config.json author_default
    title           TEXT,
    body_text       TEXT,                        -- markdown body without frontmatter
    tags_json       TEXT,                        -- JSON array of free-form tags
    related_evidence_json   TEXT,                -- JSON array of pointers into the evidence corpus
                                                 -- (paths, message IDs, document slugs)
    related_reference_json  TEXT,                -- JSON array of pointers into the optional reference DB
                                                 -- (system/reference.sqlite; empty when the reference
                                                 -- layer is not in use)
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    source_path     TEXT NOT NULL,               -- relative path to the .md file under journal/entries/
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_journal_entries_entered ON journal_entries(entered_at_iso);
CREATE INDEX IF NOT EXISTS idx_journal_entries_author ON journal_entries(author);
CREATE INDEX IF NOT EXISTS idx_journal_entries_sha ON journal_entries(sha256);

-- =========================================================================
-- FTS5 over journal title + body (full-text search)
-- =========================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS journal_entries_fts USING fts5(
    title, body_text,
    content='journal_entries', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS journal_entries_ai AFTER INSERT ON journal_entries BEGIN
    INSERT INTO journal_entries_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;
CREATE TRIGGER IF NOT EXISTS journal_entries_ad AFTER DELETE ON journal_entries BEGIN
    INSERT INTO journal_entries_fts(journal_entries_fts, rowid, title, body_text)
    VALUES('delete', old.id, old.title, old.body_text);
END;
CREATE TRIGGER IF NOT EXISTS journal_entries_au AFTER UPDATE ON journal_entries BEGIN
    INSERT INTO journal_entries_fts(journal_entries_fts, rowid, title, body_text)
    VALUES('delete', old.id, old.title, old.body_text);
    INSERT INTO journal_entries_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;

-- =========================================================================
-- Journal operations log (mirrored from system/journal-operations.log)
-- Engineering bookkeeping for the journal pipeline only.
-- (The evidence corpus's record-integrity trail is in
--  system/chain-of-custody.log -- a separate, categorically distinct log.)
-- =========================================================================
CREATE TABLE IF NOT EXISTS journal_operations (
    id              INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,               -- 'JOURNAL-WRITE', 'JOURNAL-EDIT', 'JOURNAL-BUILD', 'JOURNAL-DELETE'
    artifact_path   TEXT NOT NULL,
    sha256          TEXT,
    actor           TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_journal_ops_artifact ON journal_operations(artifact_path);
CREATE INDEX IF NOT EXISTS idx_journal_ops_event ON journal_operations(event_type);

-- =========================================================================
-- Schema version
-- =========================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));
