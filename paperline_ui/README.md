# Paperline UI

Browser-based dashboard for paperline. Replaces JSON hand-editing + CLI invocation for buyers who'd rather not touch the terminal.

## What this gives you

- **Home dashboard** — project summary, contact count, capture provider, recent reports
- **Config editor** — form-based editor for `project-config.json` (with JSON validation)
- **Run-pipeline button** — triggers `./run_pipeline.sh` (or `.ps1` on Windows); shows stdout/stderr tails
- **Scope-rule tester** — paste a synthetic message; see whether your current rules would mark it in-scope
- **Reports viewer** — browse generated reports in the browser

## Install

```bash
# From the paperline project root
pip install fastapi uvicorn 'jinja2>=3' python-multipart
```

Or, if pyproject extras are wired up:

```bash
pip install -e .[ui]
```

## Run

From the paperline project root (the folder containing `system/project-config.json`):

```bash
python -m paperline_ui
```

Browser opens at `http://127.0.0.1:8765`.

Override host/port via env vars:

```bash
PAPERLINE_UI_PORT=8001 python -m paperline_ui
```

Run against a different project root:

```bash
PAPERLINE_PROJECT_ROOT=/path/to/another-project python -m paperline_ui
```

## What this UI is NOT

- Not a hosted service. Local-only. No login, no auth (it binds 127.0.0.1 by default).
- Not a multi-user dashboard. Single user, single project at a time.
- Not a record viewer. The reports/*.md outputs are rendered; the corpus.sqlite is not (use Datasette for that).
- Not a replacement for the CLI. Power users can still edit `project-config.json` directly + run `./run_pipeline.sh` from a terminal.

## Architecture

Single FastAPI app + 5 Jinja2 templates + Bootstrap CSS from CDN. Stateless: state lives in `system/project-config.json` + `reports/`.

```
paperline_ui/
├── __init__.py
├── __main__.py        # python -m paperline_ui
├── app.py             # FastAPI routes
├── README.md          # this file
├── templates/
│   ├── base.html
│   ├── home.html
│   ├── config.html
│   ├── scope_test.html
│   └── report.html
└── static/            # empty for now; CDN-only CSS
```

## v0.2 roadmap

- Server-sent events for pipeline run (stream output instead of synchronous wait)
- Markdown-to-HTML rendering for reports (markdown-it or python-markdown)
- Datasette embed for the SQLite corpus
- Multi-project picker (switch project root without restarting)
- Form-based contacts editor (instead of raw JSON)
- Authentication for non-localhost deployment

## Security notes

This UI runs `subprocess` against the project's `run_pipeline.sh`/`.ps1`. **Only run it against project folders you trust.** If you're contemplating exposing this UI on a network, add reverse-proxy auth in front; the app intentionally doesn't ship with authentication for v0.1.
