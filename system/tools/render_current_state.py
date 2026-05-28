"""Generate reports/current-state.md -- a one-page snapshot of where the project stands.

Auto-generated from system/corpus.sqlite + on-disk artifacts. Re-run after
every capture or contract update.

Sections:
  1. As-of timestamp
  2. Latest inbound + latest outbound
  3. Active threads (last 30 days) with other party + most recent message
  4. Latest contract version per family + most-recent substantive change
  5. Filed external submissions
  6. Open / unresolved items (pulled from reports/unresolved-issues.md if present)
  7. Quick-link panel
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader  # type: ignore
from lib_provenance import REPO_ROOT, REPORTS_DIR, utcnow_iso  # type: ignore

DB_PATH = REPO_ROOT / "system" / "corpus.sqlite"
_meta = config_loader.project_meta()
USER_EMAILS = tuple(_meta.get("user_emails") or ())
PROJECT_NAME = _meta.get("name", "project")


def _is_user(email: str) -> bool:
    if not email:
        return False
    return any(u in email.lower() for u in USER_EMAILS)


def main():
    if not DB_PATH.exists():
        print(f"No DB at {DB_PATH}; run build_corpus.py first.")
        return 1
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # latest inbound + outbound (relevant only)
    cur.execute("""SELECT sent_at, from_email, from_display, subject, eml_path
                   FROM messages WHERE in_scope = 1 ORDER BY sent_at DESC""")
    rows = cur.fetchall()
    latest_in = next((r for r in rows if not _is_user(r["from_email"])), None)
    latest_out = next((r for r in rows if _is_user(r["from_email"])), None)

    # threads with their latest message + other party
    cur.execute("""SELECT t.id, t.subject_canonical, t.first_msg_at, t.last_msg_at, t.msg_count
                   FROM threads t ORDER BY t.last_msg_at DESC""")
    threads = cur.fetchall()
    cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    # contracts: latest version per family + most recent substantive diff
    cur.execute("""SELECT contract_type, version_label
                   FROM contracts
                   ORDER BY contract_type, version_label""")
    by_family: dict[str, list[str]] = {}
    for r in cur.fetchall():
        by_family.setdefault(r["contract_type"], []).append(r["version_label"])

    cur.execute("""SELECT csd.section_id, ca.contract_type, ca.version_label as v_a,
                          cb.version_label as v_b, csd.similarity
                   FROM contract_section_diffs csd
                   JOIN contracts ca ON csd.contract_a_id = ca.id
                   JOIN contracts cb ON csd.contract_b_id = cb.id
                   WHERE csd.change_type = 'modified'
                   ORDER BY ca.contract_type""")
    modifications = cur.fetchall()

    # filed external submissions
    cur.execute("SELECT agency, slug, filed_on, status FROM external_submissions ORDER BY filed_on")
    submissions = cur.fetchall()

    # ===== Compose =====
    L = []
    L.append("---")
    L.append(f"title: \"Current state -- {PROJECT_NAME}\"")
    L.append(f"generated_at: {utcnow_iso()}")
    L.append("auto_generated_by: system/tools/render_current_state.py")
    L.append("---")
    L.append("")
    L.append(f"# Current state -- {PROJECT_NAME}")
    L.append("")
    L.append(f"_Snapshot generated {utcnow_iso()}. Re-run `python system/tools/render_current_state.py` to refresh._")
    L.append("")

    L.append("## Latest activity")
    L.append("")
    if latest_in:
        L.append(f"- **Last inbound**: {latest_in['sent_at']} -- _{latest_in['subject']}_")
        L.append(f"  - From: {latest_in['from_display'] or latest_in['from_email']}")
        L.append(f"  - .eml: `{latest_in['eml_path']}`")
    else:
        L.append("- No inbound messages captured.")
    L.append("")
    if latest_out:
        L.append(f"- **Last outbound**: {latest_out['sent_at']} -- _{latest_out['subject']}_")
        L.append(f"  - From: {latest_out['from_display'] or latest_out['from_email']}")
        L.append(f"  - .eml: `{latest_out['eml_path']}`")
    else:
        L.append("- No outbound messages captured.")
    L.append("")

    # awaiting-response check
    if latest_out and latest_in:
        if latest_out["sent_at"] > latest_in["sent_at"]:
            L.append(f"- **Posture**: awaiting other-party response (last move was outbound on {latest_out['sent_at'][:10]})")
        else:
            L.append(f"- **Posture**: other party has the floor; no outbound since (last inbound on {latest_in['sent_at'][:10]})")
    L.append("")

    L.append("## Active threads (touched in last 30 days)")
    L.append("")
    L.append("| Last touched | Msgs | Subject |")
    L.append("|---|---|---|")
    active_count = 0
    for t in threads:
        if not t["last_msg_at"] or t["last_msg_at"] < cutoff:
            continue
        active_count += 1
        L.append(f"| {t['last_msg_at'][:10]} | {t['msg_count']} | {(t['subject_canonical'] or '')[:80]} |")
    if active_count == 0:
        L.append("| _(none)_ | | |")
    L.append("")
    L.append(f"_Total threads in corpus: {len(threads)}; active in last 30 days: {active_count}._")
    L.append("")

    L.append("## Contract families -- latest version per family")
    L.append("")
    L.append("| Family | Latest version | Total versions |")
    L.append("|---|---|---|")
    for fam, versions in sorted(by_family.items()):
        latest = sorted(versions)[-1] if versions else "-"
        L.append(f"| `{fam}` | `{latest}` | {len(versions)} |")
    L.append("")
    L.append(f"_Substantive (non-cosmetic) clause modifications across all families: {len(modifications)}._")
    L.append("Detail in [[reports/clause-change-comparison]].")
    L.append("")

    L.append("## Substantive contract changes (latest -> 4 most recent)")
    L.append("")
    if modifications:
        L.append("| Family | From | To | Section | Similarity |")
        L.append("|---|---|---|---|---|")
        for m in modifications[:8]:
            L.append(f"| `{m['contract_type'][:35]}` | `{m['v_a']}` | `{m['v_b']}` | `{m['section_id']}` | {m['similarity']:.4f} |")
    else:
        L.append("_(no substantive modifications recorded yet)_")
    L.append("")

    L.append("## Filed external submissions")
    L.append("")
    if submissions:
        L.append("| Filed on | Agency | Slug | Status |")
        L.append("|---|---|---|---|")
        for s in submissions:
            L.append(f"| {s['filed_on']} | {s['agency']} | `{s['slug']}` | {s['status']} |")
    else:
        L.append("_(no filings yet)_")
    L.append("")

    L.append("## Headline open items")
    L.append("")
    open_items = config_loader.report_templates().get("headline_open_items", [])
    if open_items:
        for item in open_items:
            L.append(f"- {item}")
    else:
        L.append("_(populate `report_templates.headline_open_items` in project-config.json to surface open items here)_")
    L.append("")
    L.append("Full punch list: [[reports/unresolved-issues]].")
    L.append("")

    L.append("## Quick links")
    L.append("")
    L.append("- [[INDEX]] -- master index")
    L.append("- [[reports/master-timeline]] -- chronological message + contract timeline")
    L.append("- [[reports/clause-change-comparison]] -- cross-version clause diffs")
    L.append("- [[reports/contract-version-map]] -- every contract version")
    L.append("- [[reports/pet-deposit-history]] -- pet deposit details")
    L.append("- [[reports/deadline-inconsistency]] -- the Apr 24 vs Jul 24 issue")
    # Add additional project-specific quick links by editing project-config.json
    for ql in config_loader.report_templates().get("extra_quick_links", []):
        L.append(f"- {ql}")
    L.append("- `system/corpus.sqlite` -- raw queryable database (datasette-compatible)")
    L.append("")

    out_path = REPORTS_DIR / "current-state.md"
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote {out_path}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
