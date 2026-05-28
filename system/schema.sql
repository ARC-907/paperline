-- Paperline — SQLite schema
-- SQLite 3.x with FTS5 enabled.
-- Created: 2026-05-15

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- =========================================================================
-- Threads
-- =========================================================================
CREATE TABLE IF NOT EXISTS threads (
    id              INTEGER PRIMARY KEY,
    yahoo_thread_id TEXT UNIQUE,
    subject_canonical TEXT,
    party_slugs     TEXT,            -- JSON array of party slugs
    first_msg_at    TEXT,            -- ISO 8601
    last_msg_at     TEXT,
    msg_count       INTEGER DEFAULT 0,
    notes           TEXT
);

-- =========================================================================
-- Parties
-- =========================================================================
CREATE TABLE IF NOT EXISTS parties (
    id              INTEGER PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,    -- kebab-case unique slug (e.g. 'first-last' or 'org-name')
    display_name    TEXT NOT NULL,
    role            TEXT,                    -- 'source-internal', 'source-external', 'subject-org', 'platform-notification'
    email_addresses TEXT,                    -- JSON array of normalised emails
    phone           TEXT,
    license_info    TEXT,                    -- JSON
    notes           TEXT,
    canonical       INTEGER DEFAULT 1        -- 0 = alias to another party (rare)
);

-- =========================================================================
-- Messages
-- =========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    yahoo_msg_id    TEXT UNIQUE,
    rfc822_msg_id   TEXT,                    -- when capturable from headers
    thread_id       INTEGER REFERENCES threads(id),
    sent_at         TEXT NOT NULL,           -- ISO 8601 UTC
    from_email      TEXT,
    from_display    TEXT,
    to_emails       TEXT,                    -- JSON array
    cc_emails       TEXT,                    -- JSON array
    bcc_emails      TEXT,                    -- JSON array
    subject         TEXT,
    body_text       TEXT,                    -- plaintext
    body_html_path  TEXT,                    -- path under correspondence/.../emails/
    headers_json_path TEXT,
    eml_path        TEXT,                    -- path to .eml if captured
    direction       TEXT,                    -- 'inbound' | 'outbound'
    is_draft        INTEGER DEFAULT 0,       -- always 0 in corpus; drafts go to drafts_quarantined
    has_attachments INTEGER DEFAULT 0,
    captured_at     TEXT NOT NULL,           -- ISO 8601, when retrieved
    capture_method  TEXT NOT NULL            -- 'browser-automation', 'imported-from-existing'
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_email);

-- FTS5 over message bodies + subjects
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    subject, body_text,
    content='messages', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, subject, body_text)
    VALUES (new.id, new.subject, new.body_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, body_text)
    VALUES('delete', old.id, old.subject, old.body_text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, subject, body_text)
    VALUES('delete', old.id, old.subject, old.body_text);
    INSERT INTO messages_fts(rowid, subject, body_text)
    VALUES (new.id, new.subject, new.body_text);
END;

-- =========================================================================
-- Attachments
-- =========================================================================
CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY,
    msg_id          INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    filename_as_sent TEXT NOT NULL,
    original_path   TEXT NOT NULL,           -- path under correspondence/.../attachments/
    sha256          TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    mime_type       TEXT,
    extracted_text_path TEXT,                -- path under correspondence/.../extracted/
    extracted_md_path   TEXT,
    ocr_used        INTEGER DEFAULT 0,
    extraction_status TEXT DEFAULT 'pending', -- 'pending', 'ok', 'partial', 'failed'
    extraction_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_attachments_msg ON attachments(msg_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(sha256);

CREATE VIRTUAL TABLE IF NOT EXISTS attachments_fts USING fts5(
    filename_as_sent, extracted_text,
    content=''
);
-- Population is handled in build_index.py (after extraction).

-- =========================================================================
-- Contracts (identified contract versions among attachments)
-- =========================================================================
CREATE TABLE IF NOT EXISTS contracts (
    id              INTEGER PRIMARY KEY,
    attachment_id   INTEGER REFERENCES attachments(id) ON DELETE CASCADE,  -- nullable: imported baseline contracts have no parent attachment row
    contract_type   TEXT,                    -- 'vendor-msa', 'vendor-msa-renewal', 'policy-statement', 'addendum', 'side-letter', etc.
    version_label   TEXT,                    -- 'v01', 'v02', 'as-signed-2026-04-22', etc.
    effective_date  TEXT,                    -- ISO date if known
    parties_json    TEXT,                    -- JSON: who is named in the contract
    page_count      INTEGER,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_contracts_type ON contracts(contract_type);

-- =========================================================================
-- Contract sections (clause-level decomposition)
-- =========================================================================
CREATE TABLE IF NOT EXISTS contract_sections (
    id              INTEGER PRIMARY KEY,
    contract_id     INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    section_id      TEXT NOT NULL,           -- stable ID within contract: 'sec-12.pet-provisions'
    section_path    TEXT,                    -- '12 > Pets > 12.A'
    heading         TEXT,
    text            TEXT,                    -- full clause text
    char_offset_start INTEGER,
    char_offset_end   INTEGER,
    page_start      INTEGER,
    page_end        INTEGER,
    notes           TEXT,
    UNIQUE(contract_id, section_id)
);

CREATE INDEX IF NOT EXISTS idx_sections_contract ON contract_sections(contract_id);
CREATE INDEX IF NOT EXISTS idx_sections_sec_id ON contract_sections(section_id);

CREATE VIRTUAL TABLE IF NOT EXISTS contract_sections_fts USING fts5(
    heading, text,
    content='contract_sections', content_rowid='id',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS sections_ai AFTER INSERT ON contract_sections BEGIN
    INSERT INTO contract_sections_fts(rowid, heading, text)
    VALUES (new.id, new.heading, new.text);
END;
CREATE TRIGGER IF NOT EXISTS sections_ad AFTER DELETE ON contract_sections BEGIN
    INSERT INTO contract_sections_fts(contract_sections_fts, rowid, heading, text)
    VALUES('delete', old.id, old.heading, old.text);
END;
CREATE TRIGGER IF NOT EXISTS sections_au AFTER UPDATE ON contract_sections BEGIN
    INSERT INTO contract_sections_fts(contract_sections_fts, rowid, heading, text)
    VALUES('delete', old.id, old.heading, old.text);
    INSERT INTO contract_sections_fts(rowid, heading, text)
    VALUES (new.id, new.heading, new.text);
END;

-- =========================================================================
-- Contract section diffs (cross-version)
-- =========================================================================
CREATE TABLE IF NOT EXISTS contract_section_diffs (
    id              INTEGER PRIMARY KEY,
    section_id      TEXT NOT NULL,           -- stable section ID across versions
    contract_a_id   INTEGER NOT NULL REFERENCES contracts(id),
    contract_b_id   INTEGER NOT NULL REFERENCES contracts(id),
    change_type     TEXT,                    -- 'added', 'removed', 'modified', 'unchanged'
    diff_unified    TEXT,                    -- unified diff text
    similarity      REAL,                    -- 0..1
    UNIQUE(section_id, contract_a_id, contract_b_id)
);

-- =========================================================================
-- Chain of custody (mirrored from log file for queryability)
-- =========================================================================
CREATE TABLE IF NOT EXISTS chain_of_custody (
    id              INTEGER PRIMARY KEY,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    artifact_path   TEXT NOT NULL,
    sha256          TEXT,
    actor           TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_coc_artifact ON chain_of_custody(artifact_path);
CREATE INDEX IF NOT EXISTS idx_coc_event ON chain_of_custody(event_type);

-- =========================================================================
-- Existing-folder imports (gap-fill audit)
-- =========================================================================
CREATE TABLE IF NOT EXISTS existing_folder_imports (
    id              INTEGER PRIMARY KEY,
    source_path     TEXT NOT NULL,
    target_artifact_path TEXT NOT NULL,
    gap_reason      TEXT NOT NULL,
    hash_match_with_msg_attachment_id INTEGER REFERENCES attachments(id),
    importer_decision TEXT,
    imported_at     TEXT NOT NULL
);

-- =========================================================================
-- Drafts quarantine
-- =========================================================================
CREATE TABLE IF NOT EXISTS drafts_quarantined (
    id              INTEGER PRIMARY KEY,
    path            TEXT NOT NULL,
    reason          TEXT,
    original_intent TEXT,
    associated_sent_msg_id INTEGER REFERENCES messages(id),
    quarantined_at  TEXT NOT NULL
);

-- =========================================================================
-- Verification runs
-- =========================================================================
CREATE TABLE IF NOT EXISTS verification_runs (
    id              INTEGER PRIMARY KEY,
    run_at          TEXT NOT NULL,
    files_checked   INTEGER,
    ok_count        INTEGER,
    fail_count      INTEGER,
    fail_details_json TEXT
);

-- =========================================================================
-- Schema version
-- =========================================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));
