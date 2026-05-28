"""Seed the parties table from system/project-config.json.

The SQL table stays named `parties` (schema is intentionally stable across
kit versions); the JSON key in project-config.json is `contacts[]`.

Reads the canonical contact list from project-config.json (no Python edits
needed). Idempotent -- INSERT OR REPLACE on slug.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_loader  # type: ignore
from lib_provenance import REPO_ROOT  # type: ignore

DB_PATH = REPO_ROOT / "system" / "corpus.sqlite"


def main():
    if not DB_PATH.exists():
        print("No DB; run build_corpus.py first.")
        return 1
    contacts = config_loader.contacts()
    if not contacts:
        print("No contacts in project-config.json. Edit system/project-config.json -> 'contacts'.")
        return 1
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    for c in contacts:
        cur.execute("""
            INSERT INTO parties (slug, display_name, role, email_addresses, phone, license_info, notes, canonical)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(slug) DO UPDATE SET
              display_name=excluded.display_name, role=excluded.role,
              email_addresses=excluded.email_addresses, phone=excluded.phone,
              license_info=excluded.license_info, notes=excluded.notes
        """, (c["slug"], c["display_name"], c.get("role"),
              json.dumps(c.get("email_addresses", [])),
              c.get("phone"),
              json.dumps(c["license_info"]) if c.get("license_info") else None,
              c.get("notes")))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM parties")
    print(f"contacts: {cur.fetchone()[0]} canonical entries seeded/updated from project-config.json.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
