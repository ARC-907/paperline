"""FastAPI app for the paperline UI.

Run:
    cd <paperline-project-root>
    uvicorn paperline_ui.app:app --reload

Or use the launcher:
    python -m paperline_ui

The app expects to be run from a paperline project root (the folder containing
`system/project-config.json`).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Paths ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent.resolve()
PROJECT_ROOT = Path(os.environ.get("PAPERLINE_PROJECT_ROOT", Path.cwd())).resolve()
CONFIG_PATH = PROJECT_ROOT / "system" / "project-config.json"
CORPUS_DB_PATH = PROJECT_ROOT / "system" / "corpus.sqlite"
REPORTS_DIR = PROJECT_ROOT / "reports"

app = FastAPI(title="Paperline UI", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))


# ── Helpers ────────────────────────────────────────────────────────────────
def load_config() -> dict[str, Any]:
    """Load project-config.json; return empty default if missing."""
    if not CONFIG_PATH.exists():
        return {
            "project": {"name": "", "user_emails": [""], "user_display_short": ""},
            "contacts": [],
            "scope_rules": {
                "in_scope_email_patterns": [],
                "in_scope_subject_patterns": [],
                "attachment_in_scope_patterns": [],
                "off_scope_sender_patterns": [],
            },
            "capture": {"provider": "mbox_file", "in_scope_address_whitelist": []},
        }
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_config(cfg: dict[str, Any]) -> None:
    """Write project-config.json atomically."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    tmp.replace(CONFIG_PATH)


def list_reports() -> list[dict[str, Any]]:
    """Enumerate generated reports."""
    if not REPORTS_DIR.exists():
        return []
    out = []
    for path in sorted(REPORTS_DIR.glob("*.md")):
        out.append({
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        })
    return out


def _safe_count(cur: sqlite3.Cursor, sql: str) -> int:
    """Run a COUNT query; return 0 if the table/column doesn't exist."""
    try:
        cur.execute(sql)
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def _format_bytes(n: int) -> str:
    """Render a byte count as a human-readable string."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def load_stats(db_path: Path | None = None) -> dict[str, Any]:
    """Read corpus stats from <workspace>/system/corpus.sqlite.

    Returns zeros + ``built=False`` if the database is absent so the home
    page can render a build-prompt card instead of a stats grid.
    """
    path = Path(db_path) if db_path is not None else CORPUS_DB_PATH
    if not path.exists():
        return {
            "built": False,
            "total_messages": 0,
            "total_contacts": 0,
            "total_threads": 0,
            "total_documents": 0,
            "date_range": {"min": None, "max": None},
            "last_build_timestamp": None,
            "corpus_db_size_bytes": 0,
            "corpus_db_size_human": "0 B",
        }

    size = path.stat().st_size
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        total_messages = _safe_count(cur, "SELECT COUNT(*) FROM messages")

        # Contacts = DISTINCT senders + recipients across the messages table.
        # to_emails / cc_emails / bcc_emails are stored as JSON arrays.
        contacts: set[str] = set()
        try:
            cur.execute(
                "SELECT from_email, to_emails, cc_emails, bcc_emails FROM messages"
            )
            for from_email, to_json, cc_json, bcc_json in cur.fetchall():
                if from_email:
                    contacts.add(from_email.lower())
                for blob in (to_json, cc_json, bcc_json):
                    if not blob:
                        continue
                    try:
                        for addr in json.loads(blob) or []:
                            if isinstance(addr, str) and addr:
                                contacts.add(addr.lower())
                    except (json.JSONDecodeError, TypeError):
                        continue
        except sqlite3.Error:
            pass
        total_contacts = len(contacts)

        # Threads: distinct thread_id on messages OR the threads table itself,
        # whichever has more rows (covers schemas where threads is unpopulated).
        thread_count_via_messages = _safe_count(
            cur,
            "SELECT COUNT(DISTINCT thread_id) FROM messages WHERE thread_id IS NOT NULL",
        )
        thread_count_via_table = _safe_count(cur, "SELECT COUNT(*) FROM threads")
        total_threads = max(thread_count_via_messages, thread_count_via_table)

        # Documents: attachments + letters + contracts, with safe fallbacks.
        total_documents = (
            _safe_count(cur, "SELECT COUNT(*) FROM attachments")
            + _safe_count(cur, "SELECT COUNT(*) FROM letters")
            + _safe_count(cur, "SELECT COUNT(*) FROM contracts")
        )

        date_min: str | None = None
        date_max: str | None = None
        try:
            cur.execute("SELECT MIN(sent_at), MAX(sent_at) FROM messages")
            row = cur.fetchone()
            if row:
                date_min, date_max = row[0], row[1]
        except sqlite3.Error:
            pass
    finally:
        conn.close()

    return {
        "built": True,
        "total_messages": total_messages,
        "total_contacts": total_contacts,
        "total_threads": total_threads,
        "total_documents": total_documents,
        "date_range": {"min": date_min, "max": date_max},
        "last_build_timestamp": mtime.strftime("%Y-%m-%d %H:%M UTC"),
        "corpus_db_size_bytes": size,
        "corpus_db_size_human": _format_bytes(size),
    }


def resolve_obsidian_vault(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pick the Obsidian vault target for the launch endpoint.

    Order of preference:
      1. ``cfg['meta']['obsidian_vault']`` (a path string)
      2. ``cfg['obsidian_vault']``
      3. PROJECT_ROOT itself (a ``.obsidian/`` folder ships in the workspace,
         so the repo root is the vault by default).
    """
    meta_vault = (cfg.get("meta") or {}).get("obsidian_vault")
    top_vault = cfg.get("obsidian_vault")
    vault_path = Path(meta_vault or top_vault or PROJECT_ROOT).expanduser()
    if not vault_path.is_absolute():
        vault_path = (PROJECT_ROOT / vault_path).resolve()
    return {"path": vault_path, "name": vault_path.name}


def test_scope_rule(message_meta: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Apply scope rules to a synthetic message; return verdict + matches."""
    in_scope = False
    matched: list[str] = []

    sender = message_meta.get("from", "").lower()
    subject = message_meta.get("subject", "")
    attachments = message_meta.get("attachments", "")

    for pat in rules.get("off_scope_sender_patterns", []) or []:
        if pat and re.search(pat, sender, re.IGNORECASE):
            matched.append(f"OFF-SCOPE sender match: {pat}")
            return {"in_scope": False, "matched": matched}

    for pat in rules.get("in_scope_email_patterns", []) or []:
        if pat and re.search(pat, sender, re.IGNORECASE):
            in_scope = True
            matched.append(f"in-scope email: {pat}")

    for pat in rules.get("in_scope_subject_patterns", []) or []:
        if pat and re.search(pat, subject, re.IGNORECASE):
            in_scope = True
            matched.append(f"in-scope subject: {pat}")

    for pat in rules.get("attachment_in_scope_patterns", []) or []:
        if pat and re.search(pat, attachments, re.IGNORECASE):
            in_scope = True
            matched.append(f"in-scope attachment: {pat}")

    return {"in_scope": in_scope, "matched": matched}


# ── Routes ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Dashboard: project summary + corpus stats + recent reports + run button."""
    cfg = load_config()
    reports = list_reports()
    has_config = CONFIG_PATH.exists()
    stats = load_stats()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "project_name": cfg.get("project", {}).get("name", "(unnamed project)"),
            "user_emails": cfg.get("project", {}).get("user_emails", []),
            "contact_count": len(cfg.get("contacts", []) or []),
            "reports": reports,
            "has_config": has_config,
            "project_root": str(PROJECT_ROOT),
            "capture_provider": cfg.get("capture", {}).get("provider", "(not set)"),
            "stats": stats,
        },
    )


@app.get("/launch-obsidian")
async def launch_obsidian() -> RedirectResponse:
    """302 to the ``obsidian://`` URL handler so the OS opens the vault.

    The browser will surface a "no handler registered" error if Obsidian
    isn't installed; that's the OS's job, not ours. The home page links
    to obsidian.md/download as a fallback.
    """
    cfg = load_config()
    vault = resolve_obsidian_vault(cfg)
    # `path` works without prior registration of the vault name; encode
    # the absolute path so spaces and reserved characters round-trip.
    target = f"obsidian://open?path={quote(str(vault['path']), safe='')}"
    return RedirectResponse(url=target, status_code=302)


@app.get("/config", response_class=HTMLResponse)
async def config_editor(request: Request) -> HTMLResponse:
    """Form-based editor for project-config.json."""
    cfg = load_config()
    return templates.TemplateResponse(
        request, "config.html", {"config_json": json.dumps(cfg, indent=2)}
    )


@app.post("/config")
async def config_save(request: Request, config_json: str = Form(...)) -> RedirectResponse:
    """Save updated config; redirect home on success, show error page on parse fail."""
    try:
        cfg = json.loads(config_json)
    except json.JSONDecodeError as exc:
        return templates.TemplateResponse(
            request,
            "config.html",
            {"config_json": config_json, "parse_error": str(exc)},
            status_code=400,
        )
    save_config(cfg)
    return RedirectResponse("/", status_code=303)


@app.get("/scope-test", response_class=HTMLResponse)
async def scope_test(request: Request) -> HTMLResponse:
    """Form: paste a synthetic message; see if scope rules would accept it."""
    return templates.TemplateResponse(request, "scope_test.html", {"result": None})


@app.post("/scope-test", response_class=HTMLResponse)
async def scope_test_run(
    request: Request,
    from_addr: str = Form(""),
    subject: str = Form(""),
    attachments: str = Form(""),
) -> HTMLResponse:
    cfg = load_config()
    result = test_scope_rule(
        {"from": from_addr, "subject": subject, "attachments": attachments},
        cfg.get("scope_rules", {}),
    )
    return templates.TemplateResponse(
        request,
        "scope_test.html",
        {
            "result": result,
            "from_addr": from_addr,
            "subject": subject,
            "attachments": attachments,
        },
    )


@app.post("/run")
async def run_pipeline() -> JSONResponse:
    """Trigger ./run_pipeline.sh; return captured stdout + stderr.

    Synchronous for v0.1. v0.2 should stream via SSE.
    """
    script_sh = PROJECT_ROOT / "run_pipeline.sh"
    script_ps1 = PROJECT_ROOT / "run_pipeline.ps1"
    if os.name == "nt" and script_ps1.exists():
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_ps1)]
    elif script_sh.exists():
        cmd = ["bash", str(script_sh)]
    else:
        raise HTTPException(404, f"No run_pipeline.sh or .ps1 found at {PROJECT_ROOT}")

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=600
        )
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": "pipeline timeout (10 min)"}, status_code=504)

    return JSONResponse({
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
    })


@app.get("/reports/{name}", response_class=HTMLResponse)
async def view_report(request: Request, name: str) -> HTMLResponse:
    """Render a markdown report as HTML (or as fenced code if rendering unavailable)."""
    safe_name = Path(name).name  # path-traversal guard
    path = REPORTS_DIR / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, f"Report not found: {safe_name}")
    raw = path.read_text(encoding="utf-8")
    # Lightweight rendering: just escape + wrap in <pre>. v0.2 can use markdown-it.
    return templates.TemplateResponse(
        request, "report.html", {"name": safe_name, "raw": raw}
    )


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "version": "0.1.0",
        "project_root": str(PROJECT_ROOT),
        "config_present": CONFIG_PATH.exists(),
        "reports_present": REPORTS_DIR.exists(),
    })
