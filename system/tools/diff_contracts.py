"""Cross-version clause diffs + duplicate report for the new layout.

Walks documents/<family>/<version>/decomposed.json and writes:
  - reports/contract-version-map.md
  - reports/clause-change-comparison.md
  - reports/duplicate-report.md
"""
from __future__ import annotations

import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_provenance import DOCUMENTS_DIR, REPO_ROOT, REPORTS_DIR  # type: ignore


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Build family -> [(version_label, decomposed_dict, manifest_dict, dir)]
    families: dict[str, list[dict]] = defaultdict(list)
    for fam_dir in sorted(DOCUMENTS_DIR.iterdir()):
        if not fam_dir.is_dir() or fam_dir.name.startswith("."):
            continue
        for v_dir in sorted(fam_dir.iterdir()):
            if not v_dir.is_dir():
                continue
            dec = v_dir / "decomposed.json"
            if not dec.exists():
                continue
            man = v_dir / "manifest.json"
            families[fam_dir.name].append({
                "label": v_dir.name,
                "dir": v_dir,
                "dec": _load(dec),
                "man": _load(man) if man.exists() else {},
            })

    # Populate the SQL contract_section_diffs table for agent queries
    _populate_sql_diffs(families)

    # ---------- contract-version-map.md ----------
    lines = ["# Contract version map\n",
             "| Family | Version | Date delivered | Sections | Source PDF |",
             "|---|---|---|---|---|"]
    for fam, items in families.items():
        for it in items:
            sec_count = it["dec"].get("section_count", len(it["dec"].get("sections", [])))
            sourced = it["man"].get("sourced_from", "(baseline / imported)")
            date = it["man"].get("delivered_on_date", it["label"].split("_", 1)[-1])
            lines.append(f"| `{fam}` | `{it['label']}` | {date} | {sec_count} | `{sourced}` |")
    (REPORTS_DIR / "contract-version-map.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORTS_DIR / 'contract-version-map.md'}")

    # ---------- clause-change-comparison.md ----------
    lines = ["# Clause-change comparison\n"]
    for fam, items in sorted(families.items()):
        if len(items) < 2:
            lines.append(f"## `{fam}`")
            lines.append(f"_Only one version captured ({items[0]['label']}); nothing to diff._\n")
            continue
        lines.append(f"## `{fam}` ({len(items)} versions)\n")
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            lines.append(f"### {a['label']} -> {b['label']}\n")
            rows = _diff_two(a["dec"], b["dec"])
            added = sum(1 for r in rows if r["change"] == "added")
            removed = sum(1 for r in rows if r["change"] == "removed")
            modified = sum(1 for r in rows if r["change"] == "modified")
            unchanged = sum(1 for r in rows if r["change"] == "unchanged")
            lines.append(f"_added: {added}, removed: {removed}, modified: {modified}, unchanged: {unchanged}_\n")
            for r in rows:
                if r["change"] == "unchanged":
                    continue
                lines.append(f"#### `{r['key']}` -- {r['change']} -- {r['heading']}")
                if r.get("similarity") is not None and r["change"] == "modified":
                    lines.append(f"_similarity: {r['similarity']:.3f}_")
                if r.get("diff"):
                    lines.append("```diff")
                    d = r["diff"]
                    lines.append(d[:5000] + ("\n[truncated]" if len(d) > 5000 else ""))
                    lines.append("```")
                lines.append("")
    (REPORTS_DIR / "clause-change-comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORTS_DIR / 'clause-change-comparison.md'}")

    # ---------- duplicate-report.md ----------
    by_sha: dict[str, list[dict]] = defaultdict(list)
    for fam, items in families.items():
        for it in items:
            cpdf = it["dir"] / "contract.pdf"
            if not cpdf.exists():
                continue
            files = it["man"].get("files", {})
            sha = files.get("contract.pdf", {}).get("sha256")
            if sha:
                by_sha[sha].append({"family": fam, "label": it["label"],
                                    "path": str(cpdf.relative_to(REPO_ROOT)).replace("\\", "/")})
    lines = ["# Duplicate-report (hash-identical contract PDFs)\n"]
    dupes = {sha: items for sha, items in by_sha.items() if len(items) > 1}
    if not dupes:
        lines.append("_No hash-identical duplicates._")
    else:
        for sha, items in dupes.items():
            lines.append(f"## sha256 `{sha[:16]}...` ({len(items)} copies)")
            for it in items:
                lines.append(f"- `{it['family']}/{it['label']}` -> `{it['path']}`")
            lines.append("")
    (REPORTS_DIR / "duplicate-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORTS_DIR / 'duplicate-report.md'}")
    return 0


def _populate_sql_diffs(families: dict[str, list[dict]]):
    """Insert clause-level diffs into contract_section_diffs for SQL queries."""
    import sqlite3
    db = REPO_ROOT / "system" / "corpus.sqlite"
    if not db.exists():
        print("[sql] no DB; skipping contract_section_diffs population")
        return
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("DELETE FROM contract_section_diffs")
    inserted = 0
    for fam, items in families.items():
        if len(items) < 2:
            continue
        items = sorted(items, key=lambda c: c["label"])
        # Map version_label -> contracts.id
        labels = [it["label"] for it in items]
        rows = cur.execute(
            "SELECT id, version_label FROM contracts WHERE contract_type = ? AND version_label IN ({})".format(
                ",".join("?" * len(labels))
            ),
            (fam, *labels)
        ).fetchall()
        label_to_id = {r[1]: r[0] for r in rows}
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            cid_a = label_to_id.get(a["label"])
            cid_b = label_to_id.get(b["label"])
            if cid_a is None or cid_b is None:
                continue
            for r in _diff_two(a["dec"], b["dec"]):
                try:
                    cur.execute("""INSERT INTO contract_section_diffs
                                   (section_id, contract_a_id, contract_b_id,
                                    change_type, diff_unified, similarity)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (r["key"], cid_a, cid_b, r["change"],
                                 r.get("diff", "") or None,
                                 r.get("similarity")))
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
    conn.commit()
    conn.close()
    print(f"[sql] contract_section_diffs: {inserted} rows inserted")


# Per-envelope volatile tokens that should NOT count as substantive changes.
# (Same patterns as system/tools/extract_contract.py.)
_ESIGN_URL_RE = __import__("re").compile(r"dtlp\.us/[A-Za-z0-9\-]+")
_ESIGN_VERIFICATION_LINE_RE = __import__("re").compile(
    r"e-signature verification: dtlp\.us/[A-Za-z0-9\-]+", __import__("re").I)
_ENVELOPE_ID_RE = __import__("re").compile(r"\b[A-Z0-9]{8,12}-[A-Z0-9]{4,8}-[A-Z0-9]{4,8}\b")


def _normalize_for_diff(text: str) -> str:
    if not text:
        return ""
    out = _ESIGN_VERIFICATION_LINE_RE.sub("[e-signature verification: <URL>]", text)
    out = _ESIGN_URL_RE.sub("[dtlp.us/<envelope-id>]", out)
    out = _ENVELOPE_ID_RE.sub("[envelope-id]", out)
    return out


def _diff_two(a: dict, b: dict) -> list[dict]:
    def key(sid: str) -> str:
        parts = sid.split("-", 2)
        return parts[2] if len(parts) >= 3 else sid

    a_map = {key(s["section_id"]): s for s in a.get("sections", [])}
    b_map = {key(s["section_id"]): s for s in b.get("sections", [])}
    rows = []
    for k in sorted(set(a_map) | set(b_map)):
        sa, sb = a_map.get(k), b_map.get(k)
        if sa and not sb:
            rows.append({"key": k, "change": "removed", "heading": sa.get("heading", ""), "diff": ""})
        elif sb and not sa:
            rows.append({"key": k, "change": "added", "heading": sb.get("heading", ""), "diff": ""})
        else:
            # Normalize per-envelope tokens BEFORE comparing -- so a e-signature URL
            # change without substantive text change shows as 'unchanged'.
            text_a = _normalize_for_diff(sa["text"] or "")
            text_b = _normalize_for_diff(sb["text"] or "")
            ratio = difflib.SequenceMatcher(None, text_a, text_b).ratio()
            ta = text_a.splitlines()
            tb = text_b.splitlines()
            if ratio >= 0.9999:
                # Check if RAW (pre-normalize) was identical too: if not, the
                # only change was per-envelope tokens (e-signature URL etc.)
                raw_identical = (sa["text"] or "") == (sb["text"] or "")
                rows.append({"key": k, "change": "unchanged", "heading": sa.get("heading", ""),
                             "diff": "", "similarity": ratio,
                             "envelope_only_change": not raw_identical})
            else:
                ud = "\n".join(difflib.unified_diff(ta, tb, lineterm="", fromfile="A", tofile="B", n=2))
                rows.append({"key": k, "change": "modified", "heading": sa.get("heading", ""),
                             "diff": ud, "similarity": ratio})
    return rows


if __name__ == "__main__":
    sys.exit(main())
