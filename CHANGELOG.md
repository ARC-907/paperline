# Changelog

All notable changes to Paperline are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] -- 2026-05-19

Major upgrade. Two new opt-in subsystems (journal + reference) and four
new tools.

### Added (journal subsystem)

Categorically-distinct layer alongside the evidence corpus, for the operator's
own thinking -- observations, hypotheses, open issues, to-self notes.

- `system/tools/journal.py` -- CLI: `write | read | list | query`;
  `query --with-evidence` cross-queries `system/corpus.sqlite`
- `system/tools/build_journal.py` -- rebuild `system/journal.sqlite` from the
  on-disk `journal/entries/` tree
- `system/journal-schema.sql` + `system/journal-config.json`
- `journal/README.md` + `journal/entries/.gitkeep`

### Added (reference subsystem, opt-in)

Agnostic domain-knowledge lookup layer -- regulatory codes, standards,
doctrine, technical specs, prior decision records, anything an investigation
/ records corpus needs to cross-check.
Buyers populate `reference/` with their own content; the FTS5-indexed
`system/reference.sqlite` keeps it separate from the evidence corpus.

- `system/tools/ingest_reference.py` -- ingest from configured source paths
- `system/tools/build_reference.py` -- build the FTS5 index
- `system/tools/query_reference.py` -- query (every row prefixed `[REFERENCE]`)
- `system/tools/verify_reference.py` -- integrity check
- `system/reference-config.json` -- config template (`reference_sources[]`,
  `denylist_slugs`, `skip_file_patterns`, `skip_frontmatter_status`)
- `system/reference-schema.sql` -- SQLite + FTS5 schema (reference_docs +
  reference_sections, both with FTS mirrors)
- `system/reference-operations.log` -- empty placeholder for engineering
  bookkeeping (NOT a chain of custody)
- `reference/{README.md, cases/, doctrine/, forms/, statutes/}` -- content
  scaffold; each content folder empty (buyer supplies)

### Added (new evidence-corpus tools)

- `system/tools/query_corpus.py` -- dedicated corpus query CLI with
  `text | fields | checkboxes | inspect` subcommands; `--with-reference`
  cross-queries the optional reference DB
- `system/tools/scan_annotations.py` -- scan PDF annotations + widgets +
  embedded files + JS triggers per document version; `diff` subcommand
  catches annotation changes that text-diff misses

### Added (small infrastructure)

- `INDEX.md` -- Obsidian-friendly master index template (auto-regenerable)
- `system/chain-of-custody.log` -- record-integrity audit-trail placeholder
  (paired with the existing `system/audit-log.log` to start; future
  refactor can converge them)

### Fixed

- `system/tools/lib_provenance.py`: operator-context leak
  (a specific AI-model identifier was the default value for two dataclass
  fields, `Retrieval.operator` and `append_audit_log.actor`); scrubbed to
  the generic `"agent"`.

### Deferred to v0.3+

- An automated reference puller (fetch source HTML, parse, write markdown
  with YAML frontmatter). Pullers are inherently tied to a specific source's
  site layout and licensing, so paperline ships only the manual ingest path
  for now; a configurable puller pattern is planned for v0.3.
- Reconciling the working-directory naming so a future schema can converge
  overlapping folder concepts. Deferred because a rename would be a breaking
  change for current paperline deployments.
- A broader project-config schema (richer scope rules + report templates).
  Merging it into the existing `system/project-config.json` is a v0.3 task.

### Notes

- The new tools reuse `lib_provenance.py` for provenance + audit-log
  helpers; no new third-party Python dependencies were introduced in v0.2.0.

## [0.1.0] -- 2026-05-15

Initial public release.

### Features

- **Pluggable email capture.** A `CaptureProvider` Protocol with two ready
  backends: `yahoo_browser` (Playwright over CDP against debug Chrome :9222)
  and `gmail_imap` (`imaplib.IMAP4_SSL` + Gmail App Password). New providers
  drop in via `system/tools/providers/<name>.py` + `get_provider()`.
- **Two-layer guard.** Capture narrows by query AND a per-message address
  whitelist, so irrelevant mail can never reach the corpus on disk.
- **Hash-anchored records.** Every binary gets a sibling `.provenance.json`
  + a per-folder `manifest.json` with sha256 + size. `verify_corpus.py`
  re-hashes everything and writes a per-run report.
- **Append-only audit log** (`system/audit-log.log`).
- **Document version diffs.** `extract_contract.py` decomposes any structured
  PDF (contract, agreement, terms doc) into sections; `diff_contracts.py`
  produces cross-version section diffs with per-envelope token normalization
  (e.g. e-signature URLs are scrubbed before comparing so signature noise
  doesn't pollute the diff).
- **Obsidian-ready output.** Every message, thread, and contact gets a
  Markdown note; `INDEX.md` ties the graph together.
- **SQLite + FTS5 corpus.** Browsable with [Datasette](https://datasette.io/)
  or queryable directly.
- **One-command setup + rebuild.** `bootstrap.{ps1,sh}` finds Python 3.12+,
  creates a `.venv`, installs deps, and (optionally) installs Obsidian +
  Datasette. `run_pipeline.{ps1,sh}` rebuilds the entire derived layer with
  `-SkipVerify` / `-OnlyRender` flags.

### Quality

- pytest test suite covering the pure-function critical path
  (SHA256 hashing, slugifier, Gmail IMAP query parser, scope classifier,
  capture address-whitelist guard, EML parsing).
- ruff lint + mypy type-check configured via `pyproject.toml`
  (`requires-python = ">=3.12"`).
- GitHub Actions CI runs ruff + pytest on Python 3.12 and 3.13.
- markdownlint config (`.markdownlint.json`) tuned for the kit's doc style.

### Documentation

- `README.md` -- one-page intro
- `HOW-TO-USE.md` -- step-by-step workflow including both capture providers,
  the IMAP query syntax, the two-layer guard, and adding a new provider.
- `SCHEMA.md` -- per-folder manifest formats, pointer-markdown frontmatter,
  SQLite tables, audit-log format.
- `system/design.md` -- layout + records-vs-synthesis boundary + schema-name
  stability note.
- `system/tools/README.md` -- pipeline-order tool inventory + provider matrix.
- `reports/README.md` -- what each generated report file is for.
