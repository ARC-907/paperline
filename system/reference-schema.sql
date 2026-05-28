-- Paperline -- REFERENCE subsystem SQLite schema
-- Separate physical DB from the evidence corpus (system/corpus.sqlite).
-- No shared tables, triggers, FTS namespace, or JOINs across the two DBs.
-- SQLite 3.x with FTS5 enabled.
-- Created: 2026-05-19

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- =========================================================================
-- Reference documents (one row per ingested .md file)
-- =========================================================================
CREATE TABLE IF NOT EXISTS reference_docs (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,        -- deterministic: library_subdir/relpath-no-ext
    source_path     TEXT NOT NULL,               -- absolute path of the source file (under a configured reference_sources[] entry)
    ingested_path   TEXT NOT NULL,               -- relative path under reference/doctrine/
    library_subdir  TEXT NOT NULL,               -- first path component below reference/ (e.g. 'doctrine', 'standards')
    title           TEXT,                        -- from frontmatter `title` if present
    status          TEXT,                        -- frontmatter `status`: draft, complete, etc. (stub-tagged files are filtered at ingest time)
    evidence_tier   INTEGER,                     -- 1 = verified textbook, 2 = web-validated, 3 = AI-synthesis
    category        TEXT,                        -- frontmatter `category`
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    body_text       TEXT,                        -- full markdown body (no frontmatter)
    ingested_at     TEXT NOT NULL,               -- ISO 8601 UTC
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_reference_docs_subdir ON reference_docs(library_subdir);
CREATE INDEX IF NOT EXISTS idx_reference_docs_status ON reference_docs(status);
CREATE INDEX IF NOT EXISTS idx_reference_docs_tier ON reference_docs(evidence_tier);
CREATE INDEX IF NOT EXISTS idx_reference_docs_sha ON reference_docs(sha256);

-- =========================================================================
-- Reference sections (headings within a doc, parsed at build-time)
-- =========================================================================
CREATE TABLE IF NOT EXISTS reference_sections (
    id              INTEGER PRIMARY KEY,
    doc_id          INTEGER NOT NULL REFERENCES reference_docs(id) ON DELETE CASCADE,
    section_id      TEXT NOT NULL,               -- stable ID within doc: '02.retention-period'
    heading         TEXT,                        -- 'Retention Period'
    heading_level   INTEGER,                     -- 1 = h1, 2 = h2, ...
    text            TEXT,                        -- section body (until next heading at same or higher level)
    char_offset_start INTEGER,
    char_offset_end   INTEGER,
    UNIQUE(doc_id, section_id)
);

CREATE INDEX IF NOT EXISTS idx_reference_sections_doc ON reference_sections(doc_id);

-- =========================================================================
-- FTS5 over sections (full-text search across all reference content)
-- Separate FTS namespace from the evidence corpus's messages_fts and contract_sections_fts.
-- =========================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS reference_sections_fts USING fts5(
    heading, text,
    content='reference_sections', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS reference_sections_ai AFTER INSERT ON reference_sections BEGIN
    INSERT INTO reference_sections_fts(rowid, heading, text)
    VALUES (new.id, new.heading, new.text);
END;
CREATE TRIGGER IF NOT EXISTS reference_sections_ad AFTER DELETE ON reference_sections BEGIN
    INSERT INTO reference_sections_fts(reference_sections_fts, rowid, heading, text)
    VALUES('delete', old.id, old.heading, old.text);
END;
CREATE TRIGGER IF NOT EXISTS reference_sections_au AFTER UPDATE ON reference_sections BEGIN
    INSERT INTO reference_sections_fts(reference_sections_fts, rowid, heading, text)
    VALUES('delete', old.id, old.heading, old.text);
    INSERT INTO reference_sections_fts(rowid, heading, text)
    VALUES (new.id, new.heading, new.text);
END;

-- =========================================================================
-- FTS5 over whole docs (filename + full body)
-- Useful for "is this concept in here anywhere" queries that don't care about sections.
-- =========================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS reference_docs_fts USING fts5(
    title, body_text,
    content='reference_docs', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS reference_docs_ai AFTER INSERT ON reference_docs BEGIN
    INSERT INTO reference_docs_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;
CREATE TRIGGER IF NOT EXISTS reference_docs_ad AFTER DELETE ON reference_docs BEGIN
    INSERT INTO reference_docs_fts(reference_docs_fts, rowid, title, body_text)
    VALUES('delete', old.id, old.title, old.body_text);
END;
CREATE TRIGGER IF NOT EXISTS reference_docs_au AFTER UPDATE ON reference_docs BEGIN
    INSERT INTO reference_docs_fts(reference_docs_fts, rowid, title, body_text)
    VALUES('delete', old.id, old.title, old.body_text);
    INSERT INTO reference_docs_fts(rowid, title, body_text)
    VALUES (new.id, new.title, new.body_text);
END;

-- =========================================================================
-- Reference operations log (mirrored from system/reference-operations.log)
-- Engineering bookkeeping for the reference pipeline only; it carries no
-- record-integrity weight. Categorically distinct from the corpus DB's
-- `chain_of_custody` table. Never mix events between the two: pipeline
-- activity (pulls, builds, verifications, dev corrections) belongs here;
-- evidence-handling events belong in the corpus DB's `chain_of_custody`
-- table.
-- =========================================================================
CREATE TABLE IF NOT EXISTS reference_operations (
    id              INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,               -- 'REFERENCE-INGEST', 'REFERENCE-PULL', 'REFERENCE-BUILD', 'REFERENCE-VERIFY-OK/FAIL', 'CORRECTION-*'
    artifact_path   TEXT NOT NULL,
    sha256          TEXT,
    actor           TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_ref_ops_artifact ON reference_operations(artifact_path);
CREATE INDEX IF NOT EXISTS idx_ref_ops_event ON reference_operations(event_type);

-- =========================================================================
-- Schema version
-- =========================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));
