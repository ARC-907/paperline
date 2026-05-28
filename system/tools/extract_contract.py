"""Enhanced document extraction.

For each documents/<family>/<version>/contract.{pdf,docx,md} in the corpus,
produce three sibling files:

  contract.txt              full plaintext (current behavior; everything
                            including per-envelope e-signature URLs)
  contract.normalized.txt   plaintext with per-envelope volatile tokens
                            stripped (e-signature verification URLs,
                            envelope IDs, generation timestamps). Use this
                            for diffing across versions to surface only
                            substantive content changes.
  contract.fields.json      structured extract:
                              form_fields[]   -- DroidSerif fill-in spans
                                                 (dates, amounts, names)
                              checkboxes[]    -- each Wingdings checkbox
                                                 with state + nearest
                                                 contextual text
                              signatures[]    -- e-signature blocks
                                                 (signer name + verification URL)
                              fonts_summary{} -- which fonts were used and
                                                 their span count

The shipped e-signature URL pattern matches dotloop (`dtlp.us/<envelope-id>`),
which is widely used in real-estate and other transaction workflows. Adapt
the ESIGN_URL_RE pattern to match other platforms (DocuSign, HelloSign, etc.)
as needed.

Run: python system/tools/extract_contract.py [--force]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    DOCUMENTS_DIR,
    REPO_ROOT,
    append_audit_log,
    sha256_file,
    utcnow_iso,
)

# Tokens that change per envelope but carry no substantive content:
ESIGN_URL_RE = re.compile(r"dtlp\.us/[A-Za-z0-9\-]+")
ESIGN_VERIFICATION_LINE_RE = re.compile(
    r"e-signature verification: dtlp\.us/[A-Za-z0-9\-]+", re.I)
ENVELOPE_ID_RE = re.compile(r"\b[A-Z0-9]{8,12}-[A-Z0-9]{4,8}-[A-Z0-9]{4,8}\b")

# Wingdings -> Unicode mappings used by pymupdf (most fall in U+2700 range)
CHECKBOX_GLYPHS = {
    "❑": ("checkbox", "empty"),    # ❑ Wingdings q
    "❒": ("checkbox", "empty"),    # ❒
    "❐": ("checkbox", "empty"),    # ❐
    "☑": ("checkbox", "checked"),  # ☑
    "☒": ("checkbox", "checked"),  # ☒
    "✓": ("checkmark", "checked"), # ✓
    "✔": ("checkmark", "checked"), # ✔
    "✗": ("cross", "x"),           # ✗
    "✘": ("cross", "x"),           # ✘
    "■": ("square", "filled"),     # ■
    "□": ("square", "empty"),      # □
}

FORM_FILL_FONTS = ("DroidSerif", "DroidSerif-Bold", "OpenSans", "OpenSans-Bold")


def normalize_text(text: str) -> str:
    """Strip per-envelope volatile tokens that aren't substantive content."""
    out = ESIGN_VERIFICATION_LINE_RE.sub("[e-signature verification: <URL>]", text)
    out = ESIGN_URL_RE.sub("[dtlp.us/<envelope-id>]", out)
    out = ENVELOPE_ID_RE.sub("[envelope-id]", out)
    return out


def extract_one(pdf_path: Path, force: bool = False) -> dict:
    """Returns a result dict; writes outputs alongside the input."""
    try:
        import pymupdf
    except ImportError:
        return {"status": "failed", "error": "pymupdf not installed"}
    out_txt = pdf_path.with_name("contract.txt")
    out_norm = pdf_path.with_name("contract.normalized.txt")
    out_fields = pdf_path.with_name("contract.fields.json")
    if not force and out_fields.exists():
        # Check source-hash idempotency
        try:
            prior = json.loads(out_fields.read_text(encoding="utf-8"))
            if prior.get("source_sha256") == sha256_file(pdf_path):
                return {"status": "skipped", "path": str(pdf_path.relative_to(REPO_ROOT))}
        except Exception:
            pass

    src_sha = sha256_file(pdf_path)
    doc = pymupdf.open(str(pdf_path))

    pages_text = []
    fonts_summary: dict[str, int] = {}
    form_fields: list[dict] = []
    checkboxes: list[dict] = []
    signatures: list[dict] = []

    for page_idx, page in enumerate(doc, 1):
        # Plain text per page (preserves form-feed page break)
        pages_text.append(page.get_text("text") or "")
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:    # 0 = text, 1 = image
                continue
            for line in block.get("lines", []):
                line_spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in line_spans)
                for span in line_spans:
                    text = span.get("text", "")
                    font = span.get("font", "")
                    fonts_summary[font] = fonts_summary.get(font, 0) + 1
                    bbox = span.get("bbox")
                    # form-fill detection
                    if any(font.startswith(f) for f in FORM_FILL_FONTS) and text.strip():
                        form_fields.append({
                            "page": page_idx,
                            "font": font,
                            "value": text,
                            "context_line": line_text.strip()[:120],
                            "bbox": list(bbox) if bbox else None,
                        })
                    # checkbox detection
                    for ch in text:
                        if ch in CHECKBOX_GLYPHS:
                            kind, state = CHECKBOX_GLYPHS[ch]
                            checkboxes.append({
                                "page": page_idx,
                                "glyph": ch,
                                "kind": kind,
                                "state": state,
                                "font": font,
                                "context_line": line_text.strip()[:160],
                                "bbox": list(bbox) if bbox else None,
                            })
        # signature blocks: an e-signature verification URL anchors a 3-line block
        # (signer name above, "e-signature verified" below or above, URL line itself)
        page_text = pages_text[-1]
        for m in ESIGN_VERIFICATION_LINE_RE.finditer(page_text):
            url = ESIGN_URL_RE.search(m.group()).group()
            # Find lines around the match for signer name
            before = page_text[:m.start()].splitlines()
            signer = ""
            for line in reversed(before[-5:]):
                line = line.strip()
                if not line or "e-signature verified" in line.lower():
                    continue
                # Heuristic: signer is a short capitalized name line
                if 3 <= len(line) <= 80 and any(c.isupper() for c in line):
                    signer = line
                    break
            signatures.append({
                "page": page_idx,
                "signer_inferred": signer,
                "verification_url": url,
            })

    doc.close()

    full_text = "\f".join(pages_text)
    out_txt.write_text(full_text, encoding="utf-8")
    out_norm.write_text(normalize_text(full_text), encoding="utf-8")
    payload = {
        "source_pdf": str(pdf_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source_sha256": src_sha,
        "extracted_at_iso": utcnow_iso(),
        "page_count": len(doc) if not doc.is_closed else None,
        "char_count": len(full_text),
        "fonts_summary": fonts_summary,
        "form_fields": form_fields,
        "checkboxes_summary": {
            "total": len(checkboxes),
            "empty": sum(1 for c in checkboxes if c["state"] == "empty"),
            "checked": sum(1 for c in checkboxes if c["state"] == "checked"),
            "x": sum(1 for c in checkboxes if c["state"] == "x"),
        },
        "checkboxes": checkboxes,
        "signatures": signatures,
    }
    out_fields.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    append_audit_log(
        "EXTRACT-CONTRACT", out_fields,
        sha256=sha256_file(out_fields),
        notes=f"fields={len(form_fields)} checkboxes={len(checkboxes)} sigs={len(signatures)}")
    return {
        "status": "ok",
        "path": str(pdf_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "form_fields": len(form_fields),
        "checkboxes": len(checkboxes),
        "signatures": len(signatures),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not DOCUMENTS_DIR.exists():
        print("No documents/ folder.")
        return 0
    summary = {"ok": 0, "skipped": 0, "failed": 0}
    for fam in sorted(DOCUMENTS_DIR.iterdir()):
        if not fam.is_dir() or fam.name.startswith("."):
            continue
        for v in sorted(fam.iterdir()):
            if not v.is_dir():
                continue
            pdf = v / "contract.pdf"
            if not pdf.exists():
                continue
            res = extract_one(pdf, force=args.force)
            summary[res["status"]] = summary.get(res["status"], 0) + 1
            extras = (f"  fields={res.get('form_fields')} cbx={res.get('checkboxes')} sigs={res.get('signatures')}"
                      if res["status"] == "ok" else "")
            print(f"  {res['status']:8s} {res['path']}{extras}")
    print(f"\nSummary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
