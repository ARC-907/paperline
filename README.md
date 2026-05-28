# Paperline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org)
[![Status: Beta v0.2.0](https://img.shields.io/badge/status-beta%20v0.2.0-orange.svg)](CHANGELOG.md)
[![Self-hosted](https://img.shields.io/badge/deploy-self--hosted-success.svg)]()
[![Hash-verified records](https://img.shields.io/badge/records-SHA256%20chain--of--custody-2C7BB6.svg)]()
[![SQLite FTS5](https://img.shields.io/badge/search-SQLite%20FTS5-003B57.svg?logo=sqlite&logoColor=white)]()
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A long investigation drowns in email exports and document versions. **Paperline turns that pile into a record you can search, verify, and trust a year later** — on your own machine, not a shared platform.

Self-hosted Python pipeline. Hash-verified email + document chains. Full-text searchable timeline. No cloud, no per-source fee, no shared platform.

Built for investigative reporters, compliance officers, archivists, and anyone who needs a verifiable record of correspondence + how documents changed across revisions.

> **Decision support and chronology generation from records. Not legal evidence. Not a substitute for forensic preservation.** Any chain-of-custody standard your jurisdiction or counsel requires is on you.

One folder per email, one per document version, one per memo, one per filing. Reports generate automatically: master timeline, document-version map, clause-diff between revisions, duplicate detection, hash-integrity check. See [`examples/journalism-investigation/`](examples/journalism-investigation/) for a worked example.

## What this gives you

- A **layout** that keeps records (originals + hash-verified text mirrors) cleanly separated from synthesis (reports, contact canon, design notes)
- A **build pipeline** (Python 3.12+) that walks your content folders and produces:
  - `system/corpus.sqlite` — FTS5-indexed structured database
  - `reports/master-timeline.md` — chronological timeline
  - `reports/document-version-map.md` — every document version
  - `reports/clause-change-comparison.md` — cross-version section diffs
  - `reports/duplicate-report.md` — hash-identical detection
  - `reports/verification-{ts}.md` — hash integrity check
  - `INDEX.md` — Obsidian master entry
  - `threads/`, `contacts/` Markdown notes (one per item)
  - Per-message Markdown transcripts in `correspondence/<date>/<msg>/transcript.md`
- A **records contract** — every artifact has sha256 in a sibling `manifest.json`; an audit log records every ingest, derive, and verify event.
- A **pluggable email-capture layer** — `local_mbox` (read `.mbox` files or folders of `.eml`, no credentials needed), Yahoo Mail (Playwright/CDP), and Gmail IMAP ship out of the box; a small Protocol makes adding Outlook or Proton straightforward.

## Quick start

**See it work first** — run the bundled fictional example. Then deploy on your own project.

```powershell
# Windows — see the journalism example run end-to-end (~2 min, no config edits)
.\bootstrap.ps1                                              # find Python 3.12+, create .venv, install deps
Copy-Item examples\journalism-investigation\project-config.json system\
.\run_pipeline.ps1                                           # rebuild the derived layer from the example data
# open reports\INDEX.md to see the populated output
```

```bash
# macOS / Linux / WSL
./bootstrap.sh
cp examples/journalism-investigation/project-config.json system/
./run_pipeline.sh
# open reports/INDEX.md to see the populated output
```

**To deploy on your own project:** edit `system/project-config.json` with your meta + contacts + relevance rules (the file is heavily commented), then re-run the pipeline. See [HOW-TO-USE.md](HOW-TO-USE.md) for capture-provider setup (Gmail / Yahoo / local `.mbox`).

### Capture without a live mail account (`local_mbox`)

The fastest way to use Paperline on your own data with **no credentials and no debug-Chrome session** is the `local_mbox` provider: point it at a `.mbox` file (Apple Mail / Thunderbird / mutt / Gmail Takeout all export this) or a folder of `.eml` files.

```jsonc
"capture": {
  "provider": "local_mbox",
  "mbox_path": "archives/2024-archive.mbox",   // OR set 'eml_dir' for a folder of .eml
  "search_queries": ["from:alice@example.com", "RFP-2025-014"],
  "in_scope_address_whitelist": ["alice@example.com"]
}
```

The bundled example is wired this way out of the box — `examples/journalism-investigation/project-config.json` points `local_mbox` at `examples/journalism-investigation/correspondence/_combined.mbox`, three fictional messages, no setup. See [HOW-TO-USE.md § Step 2 Option A](HOW-TO-USE.md#step-2-configure-the-capture-provider) for the full provider docs.

## Documentation

- [HOW-TO-USE.md](HOW-TO-USE.md) — step-by-step workflow, both capture providers, query syntax, two-layer guard
- [paperline_ui/README.md](paperline_ui/README.md) — browser-based UI (FastAPI dashboard for buyers who don't want to touch the CLI)
- [journal/README.md](journal/README.md) — the operator's private notes / hypotheses subsystem (separate from the evidence corpus)
- [system/design.md](system/design.md) — layout + records-vs-synthesis boundary
- [SCHEMA.md](SCHEMA.md) — `manifest.json` format + folder conventions
- [system/tools/README.md](system/tools/README.md) — every script in pipeline order
- [examples/](examples/) — what a populated message folder looks like
- [examples/journalism-investigation/](examples/journalism-investigation/) — full worked example: a fictional civic-procurement investigation with 3 emails, 2 document versions showing clause-diff, contact canon, and a tuned project-config

## Journal subsystem (operator notes)

The journal is a categorically-distinct layer (alongside the evidence corpus) for the operator's own thinking — observations, hypotheses, open issues, lines of inquiry, to-self notes. Entries live in `journal/entries/YYYY-MM-DD/HHMM_slug.md` with YAML frontmatter and are indexed into `system/journal.sqlite` for FTS.

```powershell
python system/tools/journal.py write --title "Open question" --body "Need to verify..."
python system/tools/journal.py list --limit 20
python system/tools/journal.py query "retention" --with-evidence
python system/tools/build_journal.py                # rebuild the DB from on-disk entries
```

Journal and evidence corpus share no tables / triggers / FTS namespace. The journal query CLI cross-queries on demand via `--with-evidence`. See [journal/README.md](journal/README.md) for the full discipline.

## Reference subsystem (opt-in domain lookup)

The reference layer is an **agnostic domain-knowledge lookup** that lives in its own SQLite (`system/reference.sqlite`). Buyers populate it with whatever reference material their investigation / records corpus needs to cross-check — regulatory codes, standards, technical specs, policy documents, prior decision records.

```powershell
# Edit system/reference-config.json -> fill reference_sources[] with your library paths
python system/tools/ingest_reference.py --dry-run
python system/tools/ingest_reference.py
python system/tools/build_reference.py
python system/tools/verify_reference.py
python system/tools/query_reference.py "retention period"
```

Reference DB and evidence corpus DB share no tables / triggers / FTS namespace. Cross-layer query is via `--with-reference` on the evidence query CLI. See [reference/README.md](reference/README.md) for the full discipline.

## New tools (v0.2)

- `system/tools/query_corpus.py` — query the evidence corpus directly (text + fields + checkboxes + inspect subcommands)
- `system/tools/scan_annotations.py` — scan PDF annotations / widgets / embedded files / JS triggers per document version; complements `extract_contract.py` + `diff_contracts.py` (catches changes in PDF annotations that text diff misses)
- `INDEX.md` — Obsidian-friendly master index template (auto-regenerable; populated by build pipeline)
- `system/chain-of-custody.log` — record-integrity audit trail for the evidence corpus (paired with the existing `system/audit-log.log`)

## Project status

Beta (v0.2.0). The schema and tool inventory are stable; the docs are still being polished. Issues + PRs welcome.

## License

[MIT](LICENSE).
