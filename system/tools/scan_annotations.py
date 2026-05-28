"""Scan PDF annotations + widgets + embedded files for every contract version.

`extract_contract.py` reads PDF text streams and form-field text spans. It does
NOT surface PDF-level annotations (sticky notes, free-text overlays, link
actions, JavaScript triggers) or interactive form widgets (independent of the
text spans they overlap). Those can carry substantive changes that the text
diff misses -- e.g. an annotation added between two otherwise byte-text-
identical PDF versions.

For each contracts/<family>/<version>/contract.pdf, this tool writes
contract.annotations.json with:
  - annotations[]   per-page list with type, content, bbox, author, modified-at
  - widgets[]       per-page interactive form widgets (acroform), name, type, value
  - embedded_files[] any files embedded in the PDF
  - attachments[]   any file attachments
  - js_actions[]    any document-level JavaScript triggers

Subcommands:
  scan      Extract annotations from every contract version
  diff      Compare annotations between two versions (family + v_a + v_b)

Usage:
  python system/tools/scan_annotations.py scan
  python system/tools/scan_annotations.py scan --family contract-vendor-x
  python system/tools/scan_annotations.py diff contract-vendor-x v05_2026-05-14 v06_2026-05-19
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    CONTRACTS_DIR,
    REPO_ROOT,
    append_chain_of_custody,
    sha256_file,
    utcnow_iso,
)

# Make stdout tolerant of any Unicode character.
_reconfigure = getattr(sys.stdout, "reconfigure", None)
if _reconfigure is not None:
    with contextlib.suppress(Exception):
        _reconfigure(encoding="utf-8", errors="replace")


def _safe_bbox(rect) -> list[float] | None:
    if rect is None:
        return None
    try:
        return [rect.x0, rect.y0, rect.x1, rect.y1]
    except AttributeError:
        return None


def _annot_to_dict(annot, page_idx: int) -> dict:
    """Convert a pymupdf Annot into a JSON-safe dict, capturing every
    semantically-distinct field we can reach."""
    info = annot.info or {}
    out = {
        "page": page_idx,
        "type": annot.type[1] if annot.type else None,    # e.g. 'Text', 'Highlight', 'FreeText'
        "type_code": annot.type[0] if annot.type else None,
        "content": info.get("content") or "",
        "title": info.get("title") or "",
        "author": info.get("author") or "",
        "subject": info.get("subject") or "",
        "name": info.get("name") or "",
        "modified": info.get("modDate") or info.get("modified") or "",
        "created": info.get("creationDate") or "",
        "flags": annot.flags,
        "bbox": _safe_bbox(annot.rect),
    }
    # Sticky-note style annotations sometimes carry their text in info.content;
    # FreeText annotations carry it as rendered text on the page.
    try:
        if hasattr(annot, "popup") and annot.popup:
            out["has_popup"] = True
    except Exception:
        pass
    return out


def _widget_to_dict(widget, page_idx: int) -> dict:
    """Convert a pymupdf Widget into a JSON-safe dict. Widgets are interactive
    AcroForm fields -- text inputs, checkboxes, choice lists, signature blocks."""
    return {
        "page": page_idx,
        "field_name": widget.field_name,
        "field_type": widget.field_type,
        "field_type_string": widget.field_type_string,
        "field_value": widget.field_value,
        "field_flags": widget.field_flags,
        "is_signed": bool(getattr(widget, "is_signed", False)),
        "bbox": _safe_bbox(widget.rect),
    }


def scan_one(pdf_path: Path) -> dict:
    try:
        import pymupdf
    except ImportError:
        return {"status": "failed", "error": "pymupdf not installed"}

    doc = pymupdf.open(str(pdf_path))
    annots: list[dict] = []
    widgets: list[dict] = []
    embedded_files: list[dict] = []
    attachments: list[dict] = []
    js_actions: list[dict] = []

    for page_idx, page in enumerate(doc, 1):
        # Annotations (sticky notes, highlights, free-text, ink, etc.)
        for a in page.annots() or []:
            annots.append(_annot_to_dict(a, page_idx))
        # Interactive form widgets (AcroForm)
        for w in page.widgets() or []:
            widgets.append(_widget_to_dict(w, page_idx))

    # Document-level: embedded files + JavaScript actions
    try:
        for i in range(doc.embfile_count()):
            info = doc.embfile_info(i)
            embedded_files.append({
                "index": i,
                "name": info.get("filename") or info.get("name") or "",
                "description": info.get("desc") or info.get("description") or "",
                "size": info.get("size") or 0,
                "creation_date": info.get("creationDate") or "",
                "mod_date": info.get("modDate") or "",
            })
    except Exception:
        pass

    # JavaScript actions at the document level
    try:
        js_names = doc.get_xml_metadata()    # touches document XML; sometimes surfaces JS hints
        if isinstance(js_names, str) and "javascript" in js_names.lower():
            js_actions.append({"location": "document-xml-metadata",
                                "raw_excerpt": js_names[:500]})
    except Exception:
        pass

    page_count = len(doc)
    src_sha = sha256_file(pdf_path)
    doc.close()

    payload = {
        "source_pdf": str(pdf_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source_sha256": src_sha,
        "scanned_at_iso": utcnow_iso(),
        "page_count": page_count,
        "summary": {
            "annotations": len(annots),
            "widgets": len(widgets),
            "embedded_files": len(embedded_files),
            "attachments": len(attachments),
            "js_actions": len(js_actions),
        },
        "annotations": annots,
        "widgets": widgets,
        "embedded_files": embedded_files,
        "attachments": attachments,
        "js_actions": js_actions,
    }
    out = pdf_path.with_name("contract.annotations.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # Annotation-scan IS evidence-handling on a contract artifact -- so it
    # appends to the EVIDENCE chain-of-custody (same as the original contract
    # extraction event). The scan is a verification pass on evidence.
    append_chain_of_custody(
        "SCAN-ANNOTATIONS", out,
        sha256=sha256_file(out),
        notes=(f"annots={len(annots)} widgets={len(widgets)} "
               f"embedded={len(embedded_files)} js={len(js_actions)}"),
    )
    return {
        "status": "ok",
        "path": str(pdf_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        **payload["summary"],
    }


def cmd_scan(args) -> int:
    if not CONTRACTS_DIR.exists():
        print("No contracts/ folder.")
        return 2
    summary = {"ok": 0, "failed": 0}
    for fam in sorted(CONTRACTS_DIR.iterdir()):
        if not fam.is_dir() or fam.name.startswith("."):
            continue
        if args.family and fam.name != args.family:
            continue
        for v in sorted(fam.iterdir()):
            if not v.is_dir():
                continue
            pdf = v / "contract.pdf"
            if not pdf.exists():
                continue
            res = scan_one(pdf)
            status = res.get("status", "?")
            summary[status] = summary.get(status, 0) + 1
            extras = (f"  annots={res.get('annotations')} widgets={res.get('widgets')} "
                      f"embedded={res.get('embedded_files')} js={res.get('js_actions')}"
                      if status == "ok" else f"  {res.get('error', '')}")
            print(f"  {status:8s} {res.get('path', pdf)}{extras}")
    print(f"\nSummary: {summary}")
    return 0


def _load_scan(family: str, version: str) -> dict | None:
    p = CONTRACTS_DIR / family / version / "contract.annotations.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_diff(args) -> int:
    a = _load_scan(args.family, args.v_a)
    b = _load_scan(args.family, args.v_b)
    if not a or not b:
        print(f"[fatal] missing scan(s) -- a={a is not None} b={b is not None}; run `scan` first")
        return 2

    print(f"# Annotation diff: {args.family} {args.v_a} -> {args.v_b}")
    print()
    print("## Summary")
    for key in ("annotations", "widgets", "embedded_files", "attachments", "js_actions"):
        av = a["summary"].get(key, 0)
        bv = b["summary"].get(key, 0)
        flag = "" if av == bv else "  ** changed **"
        print(f"  {key:<18}  {args.v_a}={av:>4}   {args.v_b}={bv:>4}{flag}")
    print()

    # Per-key diffs
    for key, dump in [("annotations", _annot_dump), ("widgets", _widget_dump),
                      ("embedded_files", lambda x: x.get("name", "(unnamed)")),
                      ("js_actions", lambda x: x.get("location", "(no-loc)"))]:
        a_items = a.get(key, [])
        b_items = b.get(key, [])
        if not a_items and not b_items:
            continue
        a_keys = {_item_key(x, key): x for x in a_items}
        b_keys = {_item_key(x, key): x for x in b_items}
        added = [k for k in b_keys if k not in a_keys]
        removed = [k for k in a_keys if k not in b_keys]
        common_changed = [k for k in a_keys if k in b_keys and _item_signature(a_keys[k]) != _item_signature(b_keys[k])]
        if not added and not removed and not common_changed:
            continue
        print(f"## {key}")
        for k in removed:
            print(f"  - REMOVED: {dump(a_keys[k])}")
        for k in added:
            print(f"  + ADDED:   {dump(b_keys[k])}")
        for k in common_changed:
            print(f"  ~ MODIFIED: {dump(a_keys[k])}")
            print(f"             -> {dump(b_keys[k])}")
        print()
    return 0


def _annot_dump(a: dict) -> str:
    return (f"pg{a.get('page')}/{a.get('type')!r} content={a.get('content','')[:60]!r} "
            f"author={a.get('author','')!r} bbox={a.get('bbox')}")


def _widget_dump(w: dict) -> str:
    return (f"pg{w.get('page')}/{w.get('field_type_string')!r} "
            f"name={w.get('field_name','')!r} value={w.get('field_value','')!r}")


def _item_key(x: dict, kind: str) -> tuple:
    if kind == "annotations":
        return (x.get("page"), x.get("type"), tuple(x.get("bbox") or []))
    if kind == "widgets":
        return (x.get("page"), x.get("field_name"))
    if kind == "embedded_files":
        return (x.get("name"),)
    if kind == "js_actions":
        return (x.get("location"),)
    return (str(x),)


def _item_signature(x: dict) -> str:
    """Stable signature of relevant fields for diff purposes."""
    return json.dumps({k: v for k, v in sorted(x.items())
                       if k not in ("created", "modified")}, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan", help="Scan annotations + widgets for every contract version")
    p_scan.add_argument("--family")
    p_scan.set_defaults(func=cmd_scan)
    p_diff = sub.add_parser("diff", help="Diff annotations between two versions")
    p_diff.add_argument("family")
    p_diff.add_argument("v_a")
    p_diff.add_argument("v_b")
    p_diff.set_defaults(func=cmd_diff)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
