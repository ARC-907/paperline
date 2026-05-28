# Paperline design

## Goals

1. **One name = one thing.** Every folder name describes what it contains. `correspondence/` has correspondence, `documents/` has document versions, `memos/` has memos, `filings/` has formal filings or external submissions, `system/` is machinery.
2. **No duplicated binaries.** A document or memo that came in as an email attachment lives in EXACTLY ONE place (`documents/<family>/<version>/` or `memos/<who>/<slug>/`). The email's `attachments/` folder gets a `.pointer.md` instead of the duplicated binary.
3. **Hash-verifiable records.** Every binary has sha256 + size in a sibling `manifest.json`. `verify_corpus.py` re-hashes everything; `audit-log.log` records every event.
4. **Synthesis stays separate from records.** Reports, drafts, strategy notes, AI-assisted analysis live under `reports/` or `system/`. Never mixed with `correspondence/`.

## Layout

```text
correspondence/<YYYY-MM-DD>/
  <HHMM>_<subject-slug>/                 ONE FOLDER PER EMAIL
    original.eml         pristine RFC822 (write-once)
    transcript.md        human-readable
    headers.json         parsed metadata (see SCHEMA.md)
    manifest.json        sha256 + size for everything in folder
    attachments/
      <name>.pdf         non-document / non-memo binary attachment
      <name>.txt         text mirror of binary (pymupdf, OCR fallback)
      <name>.pointer.md  pointer when the attachment is a document/memo
                         (binary lives in documents/ or memos/; pointer
                         carries SHA + canonical wikilink)

documents/<doc-family>/
  v<NN>_<YYYY-MM-DD>/                    ONE FOLDER PER DOCUMENT VERSION
    contract.pdf, contract.txt, decomposed.json, delivered-by.md, manifest.json

memos/
  from-user/<YYYY-MM-DD>_<slug>/         the project user's outbound memos
  from-other-party/<YYYY-MM-DD>_<slug>/  memos from any other party
    memo.{pdf,docx,md}, memo.txt, delivered-by.md, manifest.json

filings/<RECIPIENT>/<YYYY-MM-DD>_<slug>/
  filing PDF, exhibits, confirmation, manifest.json

threads/                                 one .md per email thread
contacts/                                one .md per canonical contact
reports/                                 generated reports
system/                                  machinery (NOT records)
  corpus.sqlite, schema.sql, design.md, audit-log.log
  tools/                                 active pipeline
drafts-quarantine/                       drafts excluded from corpus
```

## Records contract

Every file in `correspondence/`, `documents/`, `memos/`, `filings/` has its sha256 recorded in the containing folder's `manifest.json`. Pointer markdown files carry the same sha256 in YAML frontmatter so the linkage is verifiable without opening the canonical file.

`system/audit-log.log` is append-only:

```text
ISO_TIMESTAMP\tEVENT_TYPE\tARTIFACT_PATH\tSHA256\tACTOR\tNOTES
```

Event types: `INGEST`, `MEMO-INGEST`, `DOCUMENT-POINTER`, `FILING-IMPORT`, `LAYOUT-MIGRATION`, `VERIFY-OK`, `VERIFY-FAIL`.

## Build pipeline

```text
system/tools/build_corpus.py          # walks correspondence/+documents/, populates corpus.sqlite
system/tools/seed_parties.py          # canonical contact list (you customize via project-config.json)
system/tools/build_threads.py         # thread inference from RFC822 + subject
system/tools/classify_scope.py        # in_scope flag (you customize the patterns)
system/tools/diff_contracts.py        # cross-version section diffs + duplicate report
system/tools/render_obsidian.py       # INDEX.md, threads/, contacts/, transcripts
system/tools/render_current_state.py  # reports/current-state.md snapshot
system/tools/verify_corpus.py         # re-hash everything against manifests
```

## Boundary: synthesis vs records

**Records (under `correspondence/`, `documents/`, `memos/`, `filings/`):**

- Pristine `.eml`, `.pdf`, `.docx` originals
- Hash-verified text mirrors
- Manifest + provenance for every file
- Pointer markdowns

**Synthesis (under `system/` and `reports/`):**

- Strategy / drafts / analysis
- Generated reports
- Canonical contact list
- Reference material and domain notes
- AI-assisted notes

**Strictly off-limits in `correspondence/`:** synthesized strategy notes, draft documents, neutral domain research, AI-generated analysis. These belong under `system/` or `reports/`.

## Schema-name stability note

The SQL table names (`parties`, `contracts`, `letters`, `external_submissions`) are intentionally preserved across kit versions even though the user-facing directory and config-key names use the more neutral set (`contacts/`, `documents/`, `memos/`, `filings/` and `contacts[]` in `project-config.json`). This lets you upgrade Paperline without rebuilding your DB. If a CSV export or external query refers to those table names, it'll keep working.

## Open extension points

- Additional record directories (e.g. `references/`, `exhibits/`) — parallel to `documents/`, same per-folder pattern.
- `system/reference/` — domain-specific reference material (vendor specs, internal SOPs, style guides).
- Custom report scripts — drop into `system/tools/` and call from your build pipeline.
