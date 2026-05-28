"""Ingest agnostic reference material into the project's reference subsystem.

Walks the allowlisted source dirs (configured in `system/reference-config.json`),
copies eligible `.md` files into `reference/doctrine/<subdir>/<relpath>`, writes
per-file provenance sidecars, and appends REFERENCE-INGEST events to
`system/reference-operations.log` (the reference subsystem's operations log --
engineering bookkeeping, categorically distinct from the evidence corpus's
integrity/audit trail).

Hard separation guarantees:
  - source subdir must be in `reference_sources[]` allowlist (whitelist)
  - source subdir must NOT be in `denylist_slugs` (paranoid double-check)
  - per-file: skip if frontmatter `status: stub`
  - per-file: skip if filename matches any project-specific `skip_file_patterns`
  - operational events go ONLY to the reference operations log, never to the
    evidence corpus's `system/chain-of-custody.log`

Usage:
  python system/tools/ingest_reference.py --dry-run
  python system/tools/ingest_reference.py
  python system/tools/ingest_reference.py --force
  python system/tools/ingest_reference.py --subdir 00-foundations
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import (  # type: ignore
    REPO_ROOT,
    Retrieval,
    Source,
    append_operations_log,
    sha256_file,
    utcnow_iso,
    write_provenance_for_file,
)

CONFIG_PATH = REPO_ROOT / "system" / "reference-config.json"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"[fatal] reference-config.json not found at {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _parse_frontmatter(text: str) -> dict:
    """Parse a YAML-like frontmatter block (no external dep). Returns {} if absent."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out: dict = {}
    for line in block.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val.lower() in ("true", "false"):
            out[key] = val.lower() == "true"
        elif val.isdigit():
            out[key] = int(val)
        else:
            out[key] = val
    return out


def _should_skip(rel_path: Path, frontmatter: dict, cfg: dict) -> tuple[bool, str]:
    skip_status = set(cfg.get("skip_frontmatter_status", []))
    if frontmatter.get("status") in skip_status:
        return True, f"frontmatter status={frontmatter['status']!r}"
    name_lower = str(rel_path).lower().replace("\\", "/")
    for pat in cfg.get("skip_file_patterns", []):
        if pat.lower() in name_lower:
            return True, f"filename matches skip pattern {pat!r}"
    return False, ""


def _walk_md_files(src_root: Path):
    for p in src_root.rglob("*.md"):
        if p.is_file():
            yield p


def _ingest_one_subdir(src_root: Path, subdir_slug: str, cfg: dict,
                       dest_root: Path, args) -> dict:
    """Returns dict with counts and per-file results for this subdir."""
    result = {
        "subdir": subdir_slug,
        "src_root": str(src_root),
        "copied": [],
        "skipped": [],
        "errors": [],
    }
    if not src_root.exists():
        result["errors"].append(f"source root not found: {src_root}")
        return result

    ops_log_path = REPO_ROOT / cfg["reference"]["ops_log_path"]

    for src_file in _walk_md_files(src_root):
        rel = src_file.relative_to(src_root)
        try:
            text = src_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = src_file.read_text(encoding="utf-8-sig")
            except Exception as e:
                result["errors"].append(f"{rel}: read failed: {e}")
                continue

        fm = _parse_frontmatter(text)
        skip, reason = _should_skip(rel, fm, cfg)
        if skip:
            result["skipped"].append({"path": str(rel), "reason": reason})
            continue

        dest_file = dest_root / subdir_slug / rel
        if dest_file.exists() and not args.force:
            # Hash-equal => idempotent skip; hash-different => report
            src_hash = sha256_file(src_file)
            dst_hash = sha256_file(dest_file)
            if src_hash == dst_hash:
                result["skipped"].append({"path": str(rel),
                                          "reason": "already ingested (hash match)"})
            else:
                result["skipped"].append({"path": str(rel),
                                          "reason": "exists with different content; pass --force"})
            continue

        if args.dry_run:
            result["copied"].append({"path": str(rel),
                                     "dest": str(dest_file.relative_to(REPO_ROOT)).replace("\\", "/"),
                                     "status": "dry-run"})
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest_file)

        src_obj = Source(
            system="reference-import",
            subject=fm.get("title") or rel.stem,
            source_path_if_imported=str(src_file),
        )
        ret = Retrieval(
            method="imported-from-existing",
            tool=f"ingest_reference.py+library-{subdir_slug}",
            retrieved_at_iso=utcnow_iso(),
        )
        write_provenance_for_file(
            dest_file, src_obj, ret,
            notes=(f"Imported from reference source subdir {subdir_slug!r}. "
                   f"Source: {src_file}. status={fm.get('status') or '(unset)'!r}, "
                   f"evidence_tier={fm.get('evidence_tier') or '(unset)'!r}."),
        )

        append_operations_log(
            "REFERENCE-INGEST", dest_file,
            log_path=ops_log_path,
            sha256=sha256_file(dest_file),
            notes=f"subdir={subdir_slug} rel={str(rel).replace(chr(92), '/')!r}",
        )
        result["copied"].append({"path": str(rel),
                                 "dest": str(dest_file.relative_to(REPO_ROOT)).replace("\\", "/"),
                                 "status": "ok"})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report planned copies; do not write to disk.")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing reference files whose source hash has changed.")
    ap.add_argument("--subdir", action="append",
                    help="Restrict ingest to a specific subdir slug (e.g. 00-foundations). "
                         "Repeatable. Default: all allowlisted subdirs.")
    args = ap.parse_args()

    cfg = _load_config()
    dest_root = REPO_ROOT / cfg["reference"]["doctrine_root"]

    sources = cfg.get("reference_sources", [])
    if args.subdir:
        sources = [s for s in sources if s["slug"] in set(args.subdir)]
        if not sources:
            print(f"[fatal] no matching subdirs for {args.subdir!r}")
            return 2

    denylist = set(cfg.get("denylist_slugs", []))
    overall = {"dry_run": args.dry_run, "subdirs": []}
    total_copied = 0
    total_skipped = 0
    total_errors = 0
    for src in sources:
        if src["slug"] in denylist:
            print(f"[fatal] subdir {src['slug']!r} is on denylist; refusing to ingest")
            return 3
        src_root = Path(src["path"])
        r = _ingest_one_subdir(src_root, src["slug"], cfg, dest_root, args)
        overall["subdirs"].append(r)
        total_copied += len(r["copied"])
        total_skipped += len(r["skipped"])
        total_errors += len(r["errors"])

    overall["totals"] = {
        "copied": total_copied,
        "skipped": total_skipped,
        "errors": total_errors,
    }
    print(json.dumps(overall, indent=2, ensure_ascii=False))
    return 0 if total_errors == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
