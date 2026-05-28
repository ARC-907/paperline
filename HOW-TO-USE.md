# How to use Paperline

## Prerequisites

- Python 3.12+
- Optional: Tesseract on PATH (for PDF OCR fallback) and Poppler (for `pdf2image`)

## One-shot setup

```powershell
# Windows
.\bootstrap.ps1                                # creates .venv + installs deps
.\bootstrap.ps1 -WithObsidian -WithDatasette   # the same, plus Obsidian + Datasette
```

```bash
# macOS / Linux / WSL
./bootstrap.sh
./bootstrap.sh --with-obsidian --with-datasette
```

## Step 1: Configure the project

Open `system/project-config.json` — **this is the only file you edit to deploy Paperline for a different project.** No Python source changes needed.

Sections to fill in:

- `project.name` and `project.user_emails` — top-level project identity
- `contacts[]` — full canonical contact list (slug, display_name, role, email_addresses, phone, license_info, notes). Used by `seed_parties.py` (the SQL table is named `parties` for schema-stability reasons; the user-facing JSON key is `contacts`).
- `scope_rules.{in_scope_email_patterns, in_scope_subject_patterns, attachment_in_scope_patterns, off_scope_sender_patterns}` — Python regexes (case-insensitive) used by `classify_scope.py` to mark each message `in_scope = 1` (relevant) or `0` (irrelevant).
- `report_templates.{headline_open_items[], obsidian_in_scope_section_heading, extra_quick_links[]}` — project-specific text that `render_current_state.py` and `render_obsidian.py` inject into reports.
- `capture.*` — see Step 2 below.

## Step 2: Configure the capture provider

`capture.provider` selects how `capture_recent_targeted.py` retrieves messages. Three built-in options. The **offline** one (`local_mbox`) is the lowest-friction starting point — it reads from files you already have and needs no mail-account credentials. Reach for Yahoo / Gmail when you actually need live capture from an inbox.

### Option A: `local_mbox` (offline — read from .mbox file or folder of .eml)

Set `"capture": {"provider": "local_mbox", ...}`. No credentials, no debug Chrome. Useful when:

- Running the bundled fictional example end-to-end with no setup
- You exported your archive from Apple Mail / Thunderbird / mutt / Gmail Takeout (all produce `.mbox`)
- You have a folder of `.eml` files from any other mail client
- You want a deterministic synthetic corpus for testing pipeline changes

Set **exactly one** of `mbox_path` or `eml_dir`:

```jsonc
"capture": {
  "provider": "local_mbox",
  "mbox_path": "archives/2024-archive.mbox",   // ONE of these two
  "eml_dir":   "archives/exported-eml/",        // (not both)
  "search_queries": ["from:alice@example.com", "RFP-2025-014"],
  "in_scope_address_whitelist": ["alice@example.com", "..."]
}
```

`search_queries` accepts the same prefix syntax as Gmail (`from:`, `to:`, `subject:`, `since:YYYY-MM-DD`, `before:YYYY-MM-DD`, plain substrings). Matching is case-insensitive substring against the raw RFC822 source. An empty / missing list yields every message.

A single corrupt message in a large archive is skipped with a warning (printed to stderr); it does not abort the import. The two-layer whitelist guard still applies — only messages with at least one whitelisted address in From/To/Cc reach disk.

The legacy provider name `mbox_file` is accepted as an alias for `local_mbox` so older configs keep working.

### Option B: `yahoo_browser` (Yahoo Mail via Playwright)

Set `"capture": {"provider": "yahoo_browser", ...}`. Requires:

1. Chrome running with `--remote-debugging-port=9222` and a Yahoo Mail tab logged in
2. Each entry in `capture.search_queries` is a plain keyword (Yahoo URL search does NOT support `from:` / `to:` operators — use email addresses as keywords)

### Option C: `gmail_imap` (Gmail via IMAP)

Set `"capture": {"provider": "gmail_imap", ...}`. One-time setup:

1. Enable 2-factor auth on the Gmail account
2. Generate an App Password at [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (label it "Paperline" or similar)
3. Set the env var (default `GMAIL_APP_PASSWORD`) before running the capture script:
   - PowerShell: `$env:GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"`
   - Bash: `export GMAIL_APP_PASSWORD="abcdefghijklmnop"` (spaces stripped)
4. Edit `capture.gmail_username` to your Gmail address
5. `capture.search_queries` accepts richer syntax for Gmail:
   - `from:address@example.com` → IMAP `FROM`
   - `to:address@example.com` → IMAP `TO`
   - `subject:keyword` → IMAP `SUBJECT`
   - `since:YYYY-MM-DD` / `before:YYYY-MM-DD` → IMAP date filters
   - Plain term → searches both BODY and SUBJECT
   - Combinable in one query: `from:vendor@example.com since:2026-01-01`

### Two-layer guard against irrelevant pollution

Regardless of provider:

1. Provider only returns candidates matching `capture.search_queries`
2. Per message, before any disk write, the parsed RFC822 From/To/Cc must contain at least one address in `capture.in_scope_address_whitelist`. If not, the message is dropped.

This makes it structurally impossible for irrelevant mail (newsletters, promotional, system mail) to reach the corpus, even if a search query accidentally matches.

### Adding a new provider

Drop a new module in `system/tools/providers/<name>.py` that implements `enumerate(queries) -> Iterator[(msg_id, query)]`, `fetch_raw_eml(msg_id, query) -> str`, and `close()`. Register it in `providers/__init__.py:get_provider()`. Then set `capture.provider` in `project-config.json`. Suggested next: `outlook_imap` or `proton_bridge`.

## Step 3: Drop content into the layout

For each email you want to capture, create:

```
correspondence/<YYYY-MM-DD>/<HHMM>_<subject-slug>/
  original.eml         # the pristine RFC822 email
  headers.json         # parsed metadata (see SCHEMA.md for the shape)
  manifest.json        # consolidated provenance + hashes (see SCHEMA.md)
  attachments/
    <name>.pdf         # original binary attachment
    <name>.txt         # text mirror of the binary
```

For each document version, create:

```
documents/<doc-family>/v<NN>_<YYYY-MM-DD>/
  contract.pdf
  contract.txt
  decomposed.json
  delivered-by.md
  manifest.json
```

For each memo (non-document attachment that you sent or received as a message body):

```
memos/from-user/<YYYY-MM-DD>_<slug>/             # outbound from the project's "user"
memos/from-other-party/<YYYY-MM-DD>_<slug>/      # inbound from any other party
  memo.{pdf,docx,md}
  memo.txt
  delivered-by.md
  manifest.json
```

For each formal filing or external submission (regulatory complaint, support ticket, application, etc.):

```
filings/<RECIPIENT>/<YYYY-MM-DD>_<slug>/
  filing.pdf, exhibits, confirmation, manifest.json
```

When an email's attachment is also a document or a memo, the binary should live in EXACTLY ONE place (`documents/` or `memos/`). The email's `attachments/` folder gets a `.pointer.md` instead of the duplicated binary. See `examples/` for the pointer file format.

## Step 4: Run the build pipeline

One command:

```powershell
.\run_pipeline.ps1                # full rebuild
.\run_pipeline.ps1 -SkipVerify    # skip the (slow) re-hash step
.\run_pipeline.ps1 -OnlyRender    # just regenerate Obsidian + reports
```

```bash
./run_pipeline.sh
./run_pipeline.sh --skip-verify
./run_pipeline.sh --only-render
```

What it does (each step is idempotent):

```text
restructure_attachments.py   # promote attachments out of correspondence/ into documents/ or memos/
extract_contract.py          # PDF -> text + form-field decomposition for each document version
build_corpus.py              # rebuild system/corpus.sqlite from every manifest.json
seed_parties.py              # canonical contacts -> parties table
build_threads.py             # thread inference from Subject + In-Reply-To / References
classify_scope.py            # in_scope = 0/1 from scope_rules patterns
diff_contracts.py            # cross-version section diffs
render_obsidian.py           # INDEX.md, threads/, contacts/, transcripts, reports/
render_current_state.py      # reports/current-state.md snapshot
verify_corpus.py             # re-hash every file in every manifest.json
```

## Step 5: Open in Obsidian (optional)

Point Obsidian at the repository folder. The `.obsidian/` config is included so it'll recognize the vault. Graph view will surface the message ↔ thread ↔ contact ↔ document wikilinks. Use Obsidian's full-text search; for structured queries, use `system/corpus.sqlite` directly (works with [Datasette](https://datasette.io/) for a browsable UI).

## Step 6: Verify periodically

After every batch of new content:

```bash
./run_pipeline.sh --only-render   # if you want to skip the build, but verify still runs at the end
# or just:
python system/tools/verify_corpus.py
```

This re-hashes every file listed in any `manifest.json` and reports mismatches. The result lands at `reports/verification-{ts}.md` and an event is appended to `system/audit-log.log` (the audit log).

## Boundary discipline (important)

- `correspondence/`, `documents/`, `memos/`, `filings/` hold **records only** — pristine originals + hash-verified derivations.
- `reports/` and `system/` hold **synthesis** — generated reports, design notes, the canonical contact list, drafts, AI-assisted analysis.

Never mix them. If you draft a strategy memo or analyze an other-party's response, that goes in `system/notes/` or `reports/strategy/`, never in `correspondence/`.

## Extending

- Custom directories — parallel to `documents/` / `memos/` for recurring reference material (e.g. `references/` for source docs you cite, `exhibits/` for evidence packets). Same per-folder pattern.
- `system/reference/` — domain-specific reference material (style guides, vendor specs, internal SOPs). Lives under `system/` to keep the records/synthesis boundary clean.
- Custom report scripts — drop into `system/tools/` and call from your build pipeline.

## Schema versioning

`system/schema.sql` is the SQLite schema. The SQL table names (`parties`, `contracts`, `letters`, `external_submissions`) are intentionally stable across kit versions even though the user-facing directories use neutral names — this lets you upgrade Paperline without rebuilding your DB from scratch. If you change the schema, increment the version row. `build_corpus.py` recreates the DB from the schema on every run, so schema changes apply on next pipeline run.
