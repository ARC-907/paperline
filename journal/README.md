# `journal/` — operator's private notes and observations

This subtree holds the **operator's private journal entries** about the records you're working with — observations, hypotheses, open issues, lines of inquiry, to-self notes. It is **deliberately separated** from the evidence corpus (`correspondence/`, `documents/`, `filings/`, `memos/`).

## Two layers, two databases, two query prefixes

| Layer | What it holds | Database | Query prefix |
|---|---|---|---|
| **Journal** (this one) | Your own thinking, hypotheses, open issues | `system/journal.sqlite` | `[JOURNAL]` |
| **Evidence corpus** | What's been collected — emails, documents, filings, memos | `system/corpus.sqlite` | `[EVIDENCE]` |

The two databases share no tables, no triggers, no FTS namespace. The journal query CLI never JOINs across them. Cross-layer queries are supported via `--with-evidence`, which runs a second query against the evidence corpus and tags each row with its layer.

*(Forward-compatible: a future paperline release may add a third optional `reference/` layer. The journal CLI's `--with-reference` flag is a no-op unless that DB is present.)*

## Layout

```
journal/
  README.md                            ← this file
  entries/
    YYYY-MM-DD/
      HHMM_slug.md                     ← one markdown file per entry, with YAML frontmatter
      HHMM_slug.md.provenance.json     ← provenance sidecar (sha256, size, write time)
```

## How to use

```powershell
# Write a new entry
python system/tools/journal.py write --title "Title" --body "Body text"
python system/tools/journal.py write --title "Story-thread observation" --body-file path/to/draft.md --tags "open-issue,thread:foo"

# Read a specific entry (full slug, partial slug, or date + keyword)
python system/tools/journal.py read 2026-01-15/witness
python system/tools/journal.py read witness

# List recent entries
python system/tools/journal.py list --limit 20

# Search the journal (optionally against the evidence corpus too)
python system/tools/journal.py query "your search phrase"
python system/tools/journal.py query "your phrase" --with-evidence

# Rebuild the SQLite index from on-disk .md files (after manual edits)
python system/tools/build_journal.py
```

## Discipline

- **Journal entries are NOT evidence.** They are observations and hypotheses. Don't treat them as facts; treat them as pointers to verify against the evidence corpus.
- **Link out to primary sources** via `--related-evidence`. When re-reading later, follow the links and verify against the corpus.
- **Entries are immutable by default.** Don't rewrite history — if your thinking changes, write a NEW entry that supersedes the old one and reference both.

The operations log (`system/journal-operations.log`) is engineering bookkeeping for the journal pipeline only. The integrity/audit trail for the evidence corpus is tracked separately in `system/chain-of-custody.log`. Two categorically distinct logs, never mixed: journal-pipeline events here, evidence-handling events there.
