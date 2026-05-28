"""Provider-agnostic targeted capture: ONLY messages from/to known relevant
addresses, regardless of mail provider.

Reads project-config.json for:
  capture.provider                 -- "yahoo_browser" | "gmail_imap" (extensible)
  capture.search_queries     -- list[str] of search queries to enumerate
  capture.in_scope_address_whitelist -- list[str]; per-message gate before write

Two-layer guard against irrelevant pollution:
  1. Provider enumerates only candidates matching the configured queries
  2. Per-message, parsed RFC822 From/To/Cc must contain at least one
     whitelisted address. If not, drop without writing.

Bookkeeping at system/.dev-scratch/_captured_ids.json prevents re-fetching
known IDs across runs.

Usage:
  python system/tools/capture_recent_targeted.py
  python system/tools/capture_recent_targeted.py --max 5      # smoke test
"""
from __future__ import annotations

import argparse
import email
import email.policy
import email.utils
import json
import re
import sys
import traceback
from datetime import UTC
from email.header import decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader  # type: ignore
from lib_provenance import (  # type: ignore
    CORRESPONDENCE_DIR,
    REPO_ROOT,
    Retrieval,
    Source,
    append_audit_log,
    safe_slug,
    sha256_file,
    utcnow_iso,
    write_provenance_for_file,
)
from providers import get_provider  # type: ignore

BOOKKEEPING = REPO_ROOT / "system" / ".dev-scratch" / "_captured_ids.json"


def load_state() -> dict:
    if BOOKKEEPING.exists():
        try:
            return json.loads(BOOKKEEPING.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"captured": {}, "failed": {}}


def save_state(state: dict):
    BOOKKEEPING.parent.mkdir(parents=True, exist_ok=True)
    BOOKKEEPING.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _decode_hdr(s: str) -> str:
    if not s:
        return ""
    out = ""
    for txt, enc in decode_header(s):
        if isinstance(txt, bytes):
            try:
                out += txt.decode(enc or "utf-8", errors="replace")
            except Exception:
                out += txt.decode("utf-8", errors="replace")
        else:
            out += txt
    return out


def parse_eml(raw: str) -> dict:
    msg = email.message_from_string(raw, policy=email.policy.default)
    sent_at_iso = ""
    if msg.get("Date"):
        try:
            dt = email.utils.parsedate_to_datetime(msg["Date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            sent_at_iso = dt.astimezone(UTC).isoformat()
        except Exception:
            sent_at_iso = msg.get("Date", "")
    return {
        "message_id": (msg.get("Message-ID") or "").strip("<>"),
        "from": _decode_hdr(msg.get("From", "")),
        "to": [a.strip() for a in (msg.get("To", "")).split(",") if a.strip()],
        "cc": [a.strip() for a in (msg.get("Cc", "")).split(",") if a.strip()],
        "subject": _decode_hdr(msg.get("Subject", "")),
        "sent_at_iso": sent_at_iso,
        "has_attachments": any(part.get_filename() for part in msg.walk()),
    }


def is_in_scope(parsed: dict, whitelist: list[str]) -> bool:
    blob = " ".join([
        parsed.get("from") or "",
        " ".join(parsed.get("to") or []),
        " ".join(parsed.get("cc") or []),
    ]).lower()
    return any(addr.lower() in blob for addr in whitelist)


def hhmm_from_iso(iso: str) -> str:
    m = re.search(r"T(\d{2}):(\d{2})", iso or "")
    return f"{m.group(1)}{m.group(2)}" if m else "0000"


def date_from_iso(iso: str) -> str:
    return (iso or "")[:10] or "_undated"


def write_message(provider_name: str, msg_id: str, raw_eml: str, parsed: dict) -> dict:
    date_str = date_from_iso(parsed["sent_at_iso"]) or "_undated"
    hhmm = hhmm_from_iso(parsed["sent_at_iso"])
    subj_slug = safe_slug(parsed["subject"], 40)
    msg_dir = CORRESPONDENCE_DIR / date_str / f"{hhmm}_{subj_slug}"
    msg_dir.mkdir(parents=True, exist_ok=True)
    eml_path = msg_dir / "original.eml"
    headers_path = msg_dir / "headers.json"
    eml_path.write_text(raw_eml, encoding="utf-8")
    headers_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    src_obj = Source(
        system=provider_name, message_id=msg_id,
        rfc822_message_id=parsed["message_id"],
        from_=parsed["from"], to=parsed["to"], cc=parsed["cc"],
        subject=parsed["subject"], sent_at_iso=parsed["sent_at_iso"],
    )
    ret = Retrieval(method="provider-capture",
                    tool=f"providers.{provider_name}+address-filter",
                    retrieved_at_iso=utcnow_iso())
    write_provenance_for_file(eml_path, src_obj, ret)
    write_provenance_for_file(headers_path, src_obj, ret,
                              derived_from=str(eml_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                              derivation_method="email.message_from_string")
    files = {f.name: {"sha256": sha256_file(f), "size_bytes": f.stat().st_size}
             for f in sorted(msg_dir.iterdir()) if f.is_file()
             and f.name not in ("manifest.json",)
             and not f.name.endswith(".provenance.json")}
    (msg_dir / "manifest.json").write_text(json.dumps({
        "message": parsed,
        "files": files,
        "captured_via": f"provider:{provider_name}+address-filter",
        "ingested_at": utcnow_iso(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    append_audit_log("INGEST", eml_path, sha256=sha256_file(eml_path),
                            notes=f"provider={provider_name} addr-filtered subj={parsed['subject'][:60]!r}")
    return {
        "status": "ok", "msg_id": msg_id,
        "path": str(eml_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "date": date_str, "subject": parsed["subject"], "from": parsed["from"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0,
                    help="Cap total NEW captures (0 = no cap)")
    ap.add_argument("--provider", default=None,
                    help="Override project-config.json capture.provider for this run")
    args = ap.parse_args()

    state = load_state()
    cfg = config_loader.load()
    cap = cfg.get("capture", {})
    provider_name = args.provider or cap.get("provider", "yahoo_browser")
    queries = cap.get("search_queries", [])
    whitelist = cap.get("in_scope_address_whitelist", [])
    if not queries or not whitelist:
        print("[fatal] project-config.json -> capture.{search_queries, in_scope_address_whitelist} are required.")
        return 1

    print(f"[provider] {provider_name}")
    print(f"[queries]  {len(queries)} configured")
    print(f"[whitelist] {len(whitelist)} addresses")

    provider = get_provider(provider_name, cfg)
    try:
        results = {"ok": 0, "skipped-already": 0, "skipped-out-of-scope": 0,
                   "failed": 0}
        captured_count = 0
        for msg_id, kw in provider.enumerate(queries):
            if args.max and captured_count >= args.max:
                print(f"[cap] reached --max={args.max}, stopping")
                break
            if msg_id in state["captured"]:
                results["skipped-already"] += 1
                continue
            try:
                raw = provider.fetch_raw_eml(msg_id, kw)
            except Exception as e:
                results["failed"] += 1
                state["failed"][msg_id] = {"error": str(e)[:200],
                                            "failed_at": utcnow_iso()}
                print(f"FAIL {msg_id}  fetch error: {str(e)[:80]}")
                save_state(state)
                continue
            if len(raw) < 200:
                results["failed"] += 1
                state["failed"][msg_id] = {"error": f"raw too small ({len(raw)})",
                                            "failed_at": utcnow_iso()}
                continue
            parsed = parse_eml(raw)
            if not is_in_scope(parsed, whitelist):
                results["skipped-out-of-scope"] += 1
                print(f"SKIP-OOS {msg_id}  from={parsed.get('from','')[:40]!r}")
                continue
            try:
                res = write_message(provider_name, msg_id, raw, parsed)
            except Exception:
                traceback.print_exc()
                results["failed"] += 1
                continue
            state["captured"][msg_id] = {"path": res["path"],
                                          "subject": res["subject"],
                                          "date": res["date"],
                                          "from": res["from"],
                                          "captured_at": utcnow_iso()}
            captured_count += 1
            results["ok"] += 1
            print(f"OK   {msg_id} -> {res['path']}")
            save_state(state)
    finally:
        provider.close()

    print(f"\n[summary] {results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
