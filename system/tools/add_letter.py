"""Generic CLI: ingest a single letter into memos/<who>/<slug>/.

Builds the canonical letter folder with letter.{pdf,docx,md} + letter.txt
+ delivered-by.md + manifest.json, then optionally replaces a source
attachment with a pointer. Designed to be run repeatedly as new letters
arrive.

Examples:
  # Letter that came in via an email attachment in the captured corpus:
  python system/tools/add_letter.py \\
      --source path/to/letter.pdf \\
      --who from-user \\
      --slug YYYY-MM-DD_letter-slug \\
      --sender "User Name <user@example.com>" \\
      --recipient "Recipient <other@example.com>" \\
      --sent-at 2026-04-25T21:53:12+00:00 \\
      --delivered-by correspondence/<date>/<HHMM>_<msg-slug>/transcript

  # Letter sent outside the captured corpus (no in-corpus delivery message):
  python system/tools/add_letter.py \\
      --source path/to/external_letter.docx \\
      --who from-user \\
      --slug YYYY-MM-DD_external-letter \\
      --sender "User Name <your-address@example.com>" \\
      --recipient "Source Contact <source@example.com>" \\
      --sent-at 2026-04-24T00:00:00+00:00 \\
      --note "Sent direct outside the captured mailbox"
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    REPO_ROOT,
    append_audit_log,
    sha256_file,
    utcnow_iso,
)

MEMOS_DIR = REPO_ROOT / "memos"


def _docx_to_text(p: Path) -> str:
    try:
        import zipfile
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(str(p)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        root = ET.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        return "\n".join(
            "".join(t.text or "" for t in p_el.iter(f"{ns}t"))
            for p_el in root.iter(f"{ns}p")
        )
    except Exception as e:
        return f"(docx-to-text failed: {e})"


def _pdf_to_text(p: Path) -> str:
    try:
        import pymupdf
        d = pymupdf.open(str(p))
        out = "\f".join(page.get_text("text") or "" for page in d)
        d.close()
        return out
    except Exception as e:
        return f"(pdf-to-text failed: {e})"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="Path to the source binary or markdown file")
    ap.add_argument("--who", required=True, choices=["from-user", "from-other-party"],
                    help="Letter direction")
    ap.add_argument("--slug", required=True, help="Letter folder slug (typically YYYY-MM-DD_descriptive)")
    ap.add_argument("--sender", required=True, help="Sender display + email")
    ap.add_argument("--recipient", required=True, help="Recipient display + email")
    ap.add_argument("--sent-at", required=True, help="ISO-8601 sent timestamp (e.g. 2026-04-25T21:53:12+00:00)")
    ap.add_argument("--delivered-by", default=None,
                    help="Wikilink target for source message (correspondence/<date>/<msg>/transcript). "
                         "Omit for letters sent outside the captured corpus.")
    ap.add_argument("--note", default="", help="Free-form note for delivered-by.md")
    ap.add_argument("--replace-source-with-pointer", action="store_true",
                    help="If --delivered-by is set, also replace the source file with a pointer")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    if not src.exists():
        print(f"ERROR: source not found: {src}")
        return 1

    target_dir = MEMOS_DIR / args.who / args.slug
    if (target_dir / "letter.pdf").exists() or (target_dir / "letter.docx").exists() \
       or (target_dir / "letter.md").exists():
        print(f"ERROR: letter folder already populated: {target_dir.relative_to(REPO_ROOT)}")
        return 1
    target_dir.mkdir(parents=True, exist_ok=True)

    ext = src.suffix.lower()
    target_bin = target_dir / f"letter{ext}"
    shutil.copy2(str(src), str(target_bin))

    text = (_pdf_to_text(src) if ext == ".pdf"
            else _docx_to_text(src) if ext == ".docx"
            else (src.read_text(encoding="utf-8", errors="replace") if ext in (".md", ".txt") else ""))
    (target_dir / "letter.txt").write_text(text, encoding="utf-8")

    if args.delivered_by:
        delivered_md = (
            f"---\ntitle: Delivered by\n---\n\n"
            f"This letter was delivered as part of:\n\n[[{args.delivered_by}]]\n"
        )
    else:
        delivered_md = (
            f"---\ntitle: Delivery channel\n---\n\n"
            f"This letter was sent **outside the captured-mailbox path**.\n\n"
            f"- Sender: {args.sender}\n- Recipient: {args.recipient}\n"
            f"- Sent at: {args.sent_at}\n\n{args.note}\n"
        )
    (target_dir / "delivered-by.md").write_text(delivered_md, encoding="utf-8")

    files = {f.name: {"sha256": sha256_file(f), "size_bytes": f.stat().st_size}
             for f in sorted(target_dir.iterdir()) if f.name != "manifest.json"}
    manifest = {
        "letter": {
            "sender": args.sender, "recipient": args.recipient,
            "sent_at_iso": args.sent_at,
            "delivered_by_message": args.delivered_by,
            "external_to_corpus": args.delivered_by is None,
            "note": args.note,
        },
        "files": files,
        "ingested_at": utcnow_iso(),
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    append_audit_log("LETTER-INGEST", target_bin, sha256=sha256_file(target_bin),
                            notes=f"sender={args.sender} recipient={args.recipient}")
    print(f"Created: {target_dir.relative_to(REPO_ROOT)}")

    if args.replace_source_with_pointer and args.delivered_by:
        sha = sha256_file(src)
        ptr_path = src.with_suffix(".pointer.md")
        ptr_path.write_text(
            f"---\ntype: letter-pointer\n"
            f"letter_path: {target_dir.relative_to(REPO_ROOT)}\n"
            f"original_filename_as_attached: {src.name}\n"
            f"sha256: {sha}\nreplaced_at: {utcnow_iso()}\n---\n\n"
            f"# Letter attachment (pointer)\n\n"
            f"Canonical letter at:\n\n[[{target_dir.relative_to(REPO_ROOT)}/]]\n",
            encoding="utf-8")
        src.unlink()
        # If there's a sibling .txt, drop it too
        sib_txt = src.with_suffix(".txt")
        if sib_txt.exists():
            sib_txt.unlink()
        print(f"Replaced source with pointer: {src.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
