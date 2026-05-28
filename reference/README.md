# `reference/` — agnostic reference lookup layer

This subtree holds **agnostic reference material** for whatever domain you're working in — standards, regulatory codes, technical specifications, policy documents, prior decision records, anything the investigation / records corpus needs to cross-reference.

It is **architecturally separated** from the evidence corpus (`correspondence/`, `documents/`, `filings/`, `memos/`) so a full-text search for a reference concept cannot collide with a search for a contact name or a specific record in the evidence corpus.

## Hard separation rules

- **Nothing project-specific lives here.** No contact names, correspondence, documents-as-sent, or project-specific public records — those go under `correspondence/`, `documents/`, `filings/`, `memos/`.
- **Separate SQLite DB.** Built by `system/tools/build_reference.py` into `system/reference.sqlite`. Never merged with `system/corpus.sqlite`.
- **Separate operations log** (`system/reference-operations.log`) — engineering bookkeeping for the reference pipeline (ingest, DB rebuilds, verifications, dev corrections). This is pipeline housekeeping only — it carries no record-integrity weight. The integrity/audit trail for the evidence corpus lives separately in `system/chain-of-custody.log` and never receives reference-pipeline events.
- **Separate FTS namespace.** `reference_sections_fts` + `reference_docs_fts`. No JOINs across DBs.
- **Belt-and-suspenders labeling.** `query_reference.py` prefixes every emitted row with `[REFERENCE]`; the evidence query side prefixes with `[EVIDENCE]`.

## Layout

```
reference/
  README.md                ← this file
  statutes/                ← primary-source regulatory codes / standards (if applicable)
  doctrine/                ← hand-curated agnostic guidance / standards / specifications
  forms/                   ← form mechanics, blank templates
  cases/                   ← prior cases / decision records / precedents (if applicable)
```

Add more subdirectories as your domain warrants. The ingester walks the configured `reference_sources[]` paths from `system/reference-config.json` regardless of subdir name.

## How to populate

Edit `system/reference-config.json` — fill in `reference_sources[]` with `{slug, path, description}` entries pointing at your source directories. Update `denylist_slugs`, `skip_file_patterns`, `skip_frontmatter_status` to enforce content gates.

```powershell
python system/tools/ingest_reference.py --dry-run    # preview what would land
python system/tools/ingest_reference.py              # ingest
python system/tools/build_reference.py               # build the FTS5 index
python system/tools/verify_reference.py              # integrity check
python system/tools/query_reference.py "your phrase" # search
```

## Content vs filename separation

The ingest tools only check **filenames** for project-specific slugs. If a source file mentions project-specific names *inside the body*, those names will land in the reference DB. The architectural separation still holds (rows are correctly tagged `[REFERENCE]` and live in a separate FTS namespace), but a body-text search for a contact name *will* return reference hits when the source material discusses that contact. Decide your content policy at deploy time: (a) accept body-text leakage, (b) sanitize source files before ingest, (c) extend the ingester with a body-text scrub pass.

## Automated reference ingest (optional)

paperline ships only the manual ingest path (drop markdown files into `reference/`, then run `ingest_reference.py`). It does not ship an automated puller, because pullers are inherently tied to a specific source's site structure, licensing, and document layout. If you want automated reference ingest from a particular source, write a small puller for your domain following the same pattern: pull → markdown with YAML frontmatter → `ingest_reference.py` → `build_reference.py`.
