---
title: Tools (Python pipeline)
status: active
---

# system/tools/

Every script here is independently runnable, idempotent, and reads
`system/project-config.json` for project-specific behavior. No script needs
to be edited to deploy Paperline for a new project.

## Pipeline order

Run in this order. Each step writes to `system/corpus.sqlite` (rebuilt from
schema by `build_corpus.py` on every run) and/or generates files under
`reports/`, `contacts/`, `threads/`.

| # | Script | Purpose |
|---|---|---|
| 0 | `capture_recent_targeted.py` | Provider-agnostic email capture (Yahoo browser or Gmail IMAP). Reads `capture.*` from config; writes to `correspondence/<date>/<hhmm>_<slug>/`. Two-layer guard: query narrowing + per-message address whitelist. |
| 1 | `restructure_attachments.py` | Promotes document / memo attachments out of `correspondence/.../attachments/` into `documents/` or `memos/`, leaving a `.pointer.md`. Run after capture, before extract. |
| 2 | `extract_contract.py` | PDF -> text + form-field decomposition for every document version. Normalizes per-envelope tokens (e.g. e-signature URLs) so diffs are clean. |
| 3 | `build_corpus.py` | Rebuilds `system/corpus.sqlite` from every `manifest.json` on disk. Drops + recreates schema each run -- safe to re-run. |
| 4 | `seed_parties.py` | Loads canonical contact list from `project-config.json -> contacts[]` into the `parties` SQL table. |
| 5 | `build_threads.py` | Inference: groups messages into threads via Subject normalization + In-Reply-To / References headers. |
| 6 | `classify_scope.py` | Sets `messages.in_scope = 0/1` (relevant/irrelevant) from `scope_rules.*` regex patterns in project-config. |
| 7 | `diff_contracts.py` | Cross-version document section diffs. Writes `reports/clause-change-comparison.md`. |
| 8 | `render_obsidian.py` | Generates `INDEX.md`, `threads/<id>.md`, `contacts/<slug>.md`, `correspondence/.../transcript.md`, `reports/master-timeline.md`, `reports/document-inventory.md`, `reports/contract-version-map.md`. |
| 9 | `render_current_state.py` | Writes `reports/current-state.md` -- snapshot dashboard with latest activity, open items, quick links. |
| 10 | `verify_corpus.py` | Re-hashes every file in every manifest; reports mismatches. Writes `reports/verification-{timestamp}.md` and appends to `system/audit-log.log`. |

## Helpers (not part of the pipeline)

| Script | Purpose |
|---|---|
| `add_letter.py` | Hand-add a memo (PDF/DOCX) into `memos/from-user/` or `memos/from-other-party/` with manifest + provenance. (Filename retains `letter` for kit-version stability.) |
| `config_loader.py` | Loads `system/project-config.json` once and caches. Importable from any tool. |
| `lib_provenance.py` | SHA256 hashing, provenance JSON writers, audit-log writer, slug helper. |

## Schema-name stability note

Some tool filenames + SQL table names retain the kit's earlier vocabulary
(`seed_parties.py`, `add_letter.py`, `diff_contracts.py`; tables `parties`,
`contracts`, `letters`, `external_submissions`). This is intentional: the
SQL schema is stable across kit versions so external queries and CSV exports
keep working when you upgrade. The user-facing directory + config-key names
use the more neutral set (`contacts/`, `documents/`, `memos/`, `filings/`
and `contacts[]` in `project-config.json`).

## Capture providers

`providers/__init__.py` holds the `CaptureProvider` Protocol + `get_provider()`
factory. Two backends ship:

| Provider | Module | Backend | Auth |
|---|---|---|---|
| `yahoo_browser` | `providers/yahoo_browser.py` | Playwright over CDP (debug Chrome :9222) | Existing Yahoo login in the attached browser tab |
| `gmail_imap` | `providers/gmail_imap.py` | `imaplib.IMAP4_SSL` -> `imap.gmail.com:993` | Gmail App Password via env var (default `GMAIL_APP_PASSWORD`) |

Selection: set `capture.provider` in `project-config.json`, or pass
`--provider <name>` to `capture_recent_targeted.py`.

To add a third provider: drop `providers/<name>.py` exporting a class that
implements `enumerate(queries)`, `fetch_raw_eml(msg_id, query)`, `close()`.
Register it in `providers/__init__.py:get_provider()`.

## One-command rebuild

After the initial capture, the entire derived layer can be regenerated:

```powershell
.\run_pipeline.ps1
```

```bash
./run_pipeline.sh
```

See the script source for the exact command sequence (it runs steps 1-10).

## Conventions

- **Idempotent by default.** Re-running any script on already-processed input is safe.
- **No project-specific data in source.** Everything project-specific lives in `system/project-config.json`.
- **No network at build time** (after initial capture). Build steps read disk + config; only `capture_recent_targeted.py` touches the network.
- **Every write is hash-anchored.** Originals get a `.provenance.json`; aggregates get a `manifest.json` listing sha256 + size for each member file.
