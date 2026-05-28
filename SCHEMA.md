# Schema reference

## Journal entry frontmatter (`journal/entries/<date>/<HHMM>_<slug>.md`)

```yaml
---
slug: "2026-05-19/1430_retention-followup"   # deterministic: YYYY-MM-DD/HHMM_safe-slug
entered_at_iso: "2026-05-19T14:30:00Z"
author: "operator"                            # defaults to journal-config.json author_default
title: "Retention-period follow-up"
tags: ["open-issue", "thread:retention"]
related_evidence: ["correspondence/2026-04-22/1822_subject-followup/", "documents/contract-2024/v03_2025-09-12/"]
related_reference: []                         # pointers into the optional reference DB; empty when the reference layer is not in use
---

Free-form markdown body here. The body is indexed into FTS5 (title + body)
for `journal.py query` searches.
```

The journal subsystem ships its own SQLite at `system/journal.sqlite` with FTS5 over title + body. See `system/journal-schema.sql` for the full schema. Journal entries are immutable by default — write a new entry that supersedes the old one if your thinking changes.

## Per-folder `manifest.json` formats

### Message manifest (`correspondence/<date>/<msg>/manifest.json`)

```json
{
  "message": {
    "rfc822_message_id": "abc123@example.com",
    "from": "Sender Name <sender@example.com>",
    "to": ["recipient@example.com"],
    "cc": [],
    "bcc": [],
    "subject": "Subject line",
    "sent_at_iso": "2026-04-22T18:22:46+00:00",
    "has_attachments": true
  },
  "files": {
    "original.eml":  {"sha256": "...", "size_bytes": 12345},
    "headers.json":  {"sha256": "...", "size_bytes": 678},
    "transcript.md": {"sha256": "...", "size_bytes": 4321},
    "attachments/proposal.pdf": {"sha256": "...", "size_bytes": 100000},
    "attachments/proposal.txt": {"sha256": "...", "size_bytes": 8000}
  },
  "captured_via": "browser-automation",
  "migrated_at": "2026-05-15T20:00:00Z"
}
```

### Document version manifest (`documents/<family>/<version>/manifest.json`)

```json
{
  "contract_family": "vendor-msa",
  "version_label": "v01_2026-04-22",
  "delivered_on_date": "2026-04-22",
  "files": {
    "contract.pdf":     {"sha256": "...", "size_bytes": 100000},
    "contract.txt":     {"derived_from": "contract.pdf", "method": "pymupdf"},
    "decomposed.json":  {"derived_from": "contract.txt", "method": "extract_contract.py"}
  },
  "sourced_from_external_origin": "(provenance-only field, no longer load-bearing for the corpus)",
  "migrated_at": "..."
}
```

### Memo manifest (`memos/<who>/<slug>/manifest.json`)

```json
{
  "letter": {
    "sender": "User Name <user@example.com>",
    "recipient": "Other Party <other@example.com>",
    "sent_at_iso": "2026-04-25T21:53:12+00:00",
    "delivered_by_message": "correspondence/2026-04-25/2153_memo/transcript",
    "external_to_user_corpus": false,
    "note": "Free-form note explaining channel"
  },
  "files": { "memo.pdf": {"sha256": "...", "size_bytes": 12345} }
}
```

### Filing manifest (`filings/<recipient>/<slug>/manifest.json`)

```json
{
  "submission": {
    "recipient": "Better Business Bureau",
    "against": "Other Party Org",
    "filed_on": "2026-05-05",
    "submission_id": "BBB-NNN",
    "status": "filed (confirmation received)"
  },
  "files": { "filing.pdf": {"sha256": "...", "size_bytes": 12345} }
}
```

## Pointer markdown frontmatter

When an attachment is a document or memo that lives elsewhere:

```yaml
---
type: contract-pointer            # or letter-pointer
contract_family: vendor-msa                    # contract-pointer only
contract_version: v01_2026-04-22               # contract-pointer only
letter_path: memos/from-user/2026-04-25_memo   # letter-pointer only
target_path: documents/.../...                 # generic alternative
original_filename_as_sent: proposal.pdf
sha256: <sha256 of canonical binary>
size_bytes: 100000
replaced_at: 2026-05-15T20:00:00Z
---
```

The pointer markdown body links to the canonical location with an Obsidian wikilink:

```markdown
# Pointer

Canonical artifact:

[[documents/vendor-msa/v01_2026-04-22/]]
```

## SQLite schema

See `system/schema.sql`. Tables (the names use the kit's stable internal vocabulary; the user-facing directories use the neutral set — see [system/design.md](system/design.md#schema-name-stability-note)):

| Table | Purpose |
|---|---|
| `messages` | one row per email message |
| `attachments` | one row per attachment binary OR pointer |
| `contracts` | one row per document version |
| `contract_sections` | section-level rows (FTS5-indexed) |
| `parties` | canonical contact list (seeded by `seed_parties.py`) |
| `letters` | one row per memo |
| `external_submissions` | one row per filing |
| `threads` | inferred from RFC822 In-Reply-To/References + subject normalization |
| `audit log` | mirror of the append-only audit log |
| `messages_fts`, `attachments_fts`, `contract_sections_fts` | FTS5 virtual tables |

## Audit log format

`system/audit-log.log` is append-only, tab-separated:

```text
ISO_TIMESTAMP\tEVENT_TYPE\tARTIFACT_PATH\tSHA256\tACTOR\tNOTES
```

Event types:

- `INGEST` — file written to corpus from an external source
- `MEMO-INGEST` — memo written to memos/
- `DOCUMENT-POINTER` — attachment binary replaced by pointer
- `FILING-IMPORT` — file imported into filings/
- `LAYOUT-MIGRATION` — structural reorganization
- `VERIFY-OK` / `VERIFY-FAIL` — verify_corpus.py run results

The log is preserved across the lifetime of the repository and never rewritten.
