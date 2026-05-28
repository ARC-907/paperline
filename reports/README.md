# reports/

Generated synthesis. Every file here is produced by `system/tools/render_*.py`
or `system/tools/verify_corpus.py` and rebuilt from the canonical records
under `correspondence/`, `documents/`, `memos/`, `filings/`.

## What lands here

| File pattern | Producer | Purpose |
|---|---|---|
| `current-state.md` | `render_current_state.py` | Snapshot dashboard (latest activity, open items, quick links) |
| `master-timeline.md` | `render_obsidian.py` | Chronological message + document timeline (relevant + irrelevant split) |
| `document-inventory.md` | `render_obsidian.py` | Audit-log dump (every verify/ingest event) |
| `clause-change-comparison.md` | `diff_contracts.py` | Cross-version document section diffs (substantive only) |
| `contract-version-map.md` | `render_obsidian.py` | Every document version with metadata |
| `verification-{TIMESTAMP}.md` | `verify_corpus.py` | Per-run hash check; ok/fail counts |
| `unresolved-issues.md` | project-specific (drop in by hand) | Open punch list |

## Boundary

This directory is **synthesis** — never put pristine records here. Originals
live in `correspondence/`, `documents/`, `memos/`, `filings/`
under hash-verified manifests.

Custom project-specific reports can live alongside the auto-generated ones; link them from `report_templates.extra_quick_links` in `system/project-config.json` so they appear in `current-state.md`.
