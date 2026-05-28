"""Replace contract / letter attachment binaries with .pointer.md files.

For each attachment in correspondence/<date>/<msg>/attachments/ whose SHA256
matches a canonical contract.pdf or letter.{pdf,docx,md} elsewhere in the
repo, delete the binary + its .txt mirror, then write a sibling .pointer.md
file referencing the canonical location. Updates the per-folder manifest.json.

Run:
  python system/tools/restructure_attachments.py [--dry-run]

Idempotent: skips items where pointer already exists.

This script eliminates the duplication that occurs when an email's attachment
is also a contract or letter that has its own canonical home in documents/
or memos/. After running, each contract/letter binary lives in EXACTLY ONE
place; the email's attachments/ folder shows the linkage via a markdown
pointer that carries the SHA256 + canonical wikilink in YAML frontmatter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    CORRESPONDENCE_DIR,
    DOCUMENTS_DIR,
    REPO_ROOT,
    append_audit_log,
    sha256_file,
    utcnow_iso,
)

MEMOS_DIR = REPO_ROOT / "memos"


def index_canonical_by_sha() -> dict[str, dict]:
    """sha256 -> {kind: 'contract'|'letter', target_dir, rel_path}"""
    idx: dict[str, dict] = {}
    if DOCUMENTS_DIR.exists():
        for fam in DOCUMENTS_DIR.iterdir():
            if not fam.is_dir() or fam.name.startswith("."):
                continue
            for v in fam.iterdir():
                if not v.is_dir():
                    continue
                cpdf = v / "contract.pdf"
                if cpdf.exists():
                    idx[sha256_file(cpdf)] = {
                        "kind": "contract", "target_dir": v,
                        "rel_path": str(cpdf.relative_to(REPO_ROOT)).replace("\\", "/"),
                        "family": fam.name, "version": v.name,
                    }
    if MEMOS_DIR.exists():
        for who in MEMOS_DIR.iterdir():
            if not who.is_dir():
                continue
            for slug in who.iterdir():
                if not slug.is_dir():
                    continue
                for cand in slug.iterdir():
                    if cand.is_file() and cand.stem == "letter" and cand.suffix.lower() in (".pdf", ".docx", ".md"):
                        idx[sha256_file(cand)] = {
                            "kind": "letter", "target_dir": slug,
                            "rel_path": str(cand.relative_to(REPO_ROOT)).replace("\\", "/"),
                            "letter_path": str(slug.relative_to(REPO_ROOT)).replace("\\", "/"),
                        }
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    canonical = index_canonical_by_sha()
    print(f"Indexed {len(canonical)} canonical artifacts (documents + memos).")

    replaced = 0
    skipped = 0

    if not CORRESPONDENCE_DIR.exists():
        print("No correspondence/ folder; nothing to do.")
        return 0

    for date_dir in sorted(CORRESPONDENCE_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        for msg_dir in sorted(date_dir.iterdir()):
            if not msg_dir.is_dir() or msg_dir.name in ("imports",):
                continue
            att_dir = msg_dir / "attachments"
            if not att_dir.exists():
                continue
            mp = msg_dir / "manifest.json"
            try:
                manifest = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"files": {}}
            except Exception:
                manifest = {"files": {}}
            for f in sorted(att_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in (".pdf", ".docx", ".doc", ".md"):
                    continue
                if f.name.endswith(".pointer.md"):
                    continue
                sha = sha256_file(f)
                hit = canonical.get(sha)
                if not hit:
                    skipped += 1
                    continue
                pointer_path = f.with_suffix(".pointer.md")
                if pointer_path.exists():
                    skipped += 1
                    continue
                txt_path = f.with_suffix(".txt")
                if hit["kind"] == "contract":
                    pointer_md = (
                        f"---\ntype: contract-pointer\n"
                        f"contract_family: {hit['family']}\n"
                        f"contract_version: {hit['version']}\n"
                        f"original_filename_as_sent: {f.name}\n"
                        f"sha256: {sha}\n"
                        f"size_bytes: {f.stat().st_size}\n"
                        f"replaced_at: {utcnow_iso()}\n---\n\n"
                        f"# Contract attachment (pointer)\n\n"
                        f"Canonical contract location:\n\n"
                        f"[[{hit['rel_path'].replace('contract.pdf', '')}]]\n\n"
                        f"- Family: `{hit['family']}`\n"
                        f"- Version: `{hit['version']}`\n"
                        f"- Original filename: `{f.name}`\n"
                        f"- SHA256 (matches canonical): `{sha}`\n"
                    )
                else:
                    pointer_md = (
                        f"---\ntype: letter-pointer\n"
                        f"letter_path: {hit['letter_path']}\n"
                        f"original_filename_as_attached: {f.name}\n"
                        f"sha256: {sha}\n"
                        f"size_bytes: {f.stat().st_size}\n"
                        f"replaced_at: {utcnow_iso()}\n---\n\n"
                        f"# Letter attachment (pointer)\n\n"
                        f"Canonical letter location:\n\n"
                        f"[[{hit['letter_path']}/]]\n\n"
                        f"- Original filename: `{f.name}`\n"
                        f"- SHA256 (matches canonical): `{sha}`\n"
                    )
                if args.dry_run:
                    print(f"  DRY  would replace {f.relative_to(REPO_ROOT)} -> {hit['kind']} pointer")
                else:
                    pointer_path.write_text(pointer_md, encoding="utf-8")
                    f.unlink()
                    if txt_path.exists():
                        txt_path.unlink()
                    files = manifest.get("files", {})
                    files.pop(f"attachments/{f.name}", None)
                    files.pop(f"attachments/{txt_path.name}", None)
                    files[f"attachments/{pointer_path.name}"] = {
                        "type": f"{hit['kind']}-pointer",
                        "canonical_path": hit.get("rel_path") or hit.get("letter_path"),
                        "original_sha256": sha,
                        "original_size_bytes": f.stat().st_size if f.exists() else None,
                    }
                    manifest["files"] = files
                    append_audit_log(
                        f"{hit['kind'].upper()}-POINTER", pointer_path, sha256=sha,
                        notes=f"replaced binary; canonical={hit.get('rel_path') or hit.get('letter_path')}")
                    print(f"  OK   {f.name} -> {hit['kind']} pointer to {hit.get('rel_path') or hit.get('letter_path')}")
                replaced += 1
            if not args.dry_run:
                mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nSummary: replaced={replaced}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
