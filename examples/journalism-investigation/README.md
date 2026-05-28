# Journalism Investigation — Worked Example

This example demonstrates Paperline applied to an investigative-journalism workflow. A reporter is investigating a fictional city procurement contract awarded under unclear circumstances. They have:

- 3 emails between themselves and two sources (one inside the city, one a former vendor employee)
- 2 versions of the city's published 2025 technology budget showing changed line items
- Contact canon for the two sources

Run this example end-to-end to see what Paperline produces for this kind of record-keeping.

## Scenario (synthetic)

The reporter ("J. Reporter") is investigating a single-source contract awarded by the fictional city of "Halverton" to "Civic Vector Inc." for $4.2M. Two sources:

- **`source-alpha`** — a city employee (anonymous) who tipped off the reporter about timing irregularities in the bid window
- **`vendor-x-source`** — a former Civic Vector engineer with knowledge of the procurement process

All names, dollar amounts, dates, and entities below are FICTIONAL. This example is for product demonstration only.

## Run the example

From the paperline repo root:

```bash
# Copy this example's project-config to the active config slot
cp examples/journalism-investigation/project-config.json system/project-config.json

# Move the example records into the live folders (or symlink, or use --content-root once that exists)
cp -r examples/journalism-investigation/correspondence/* correspondence/
cp -r examples/journalism-investigation/documents/* documents/
cp -r examples/journalism-investigation/contacts/* contacts/

# Build
./run_pipeline.sh

# Inspect outputs
ls reports/
open reports/master-timeline.md
open reports/document-version-map.md
open reports/clause-change-comparison.md
```

## What you'll see in the output

- **`reports/master-timeline.md`** — chronological view of the 3 messages + 2 document versions
- **`reports/document-version-map.md`** — both versions of the 2025 technology budget side-by-side with their hashes
- **`reports/clause-change-comparison.md`** — the line items that changed between v1 and v2 of the budget (highlighting the Civic Vector contract entry)
- **`reports/duplicate-report.md`** — empty for this small example, but demonstrates the duplicate-detection report shape
- **`reports/verification-{ts}.md`** — hash-integrity check across all artifacts
- **`INDEX.md`** — Obsidian-ready vault home page

## What this example demonstrates

1. **Multi-source correspondence captured as structured records.** Each email is its own folder with a manifest, the raw eml (or in this case a placeholder), and a Markdown transcript.
2. **Document version chains.** Two versions of the same budget document, hash-verified, with the diff surfaced automatically.
3. **Source canon.** Contacts kept in their own folder with full attribution metadata.
4. **The records-vs-synthesis boundary.** Records (`correspondence/`, `documents/`, `contacts/`) are immutable inputs. Reports (`reports/`) are derived outputs that regenerate when you re-run the pipeline.

## Adapting this to your own investigation

1. Replace the `contacts[]` entries in `project-config.json` with your real sources (kept locally; not shipped)
2. Replace the `scope_rules` patterns to match your investigation's relevant email addresses + subject keywords
3. Drop your own emails into `correspondence/<date>/<msg>/`
4. Drop document versions into `documents/`
5. Re-run the pipeline

Your records stay on your disk. No cloud, no telemetry, no shared platform.

## Caveats

- All names and amounts in this example are fictional. No connection to any real city, person, or company.
- The `.eml` and `.pdf` files in this example are PLACEHOLDERS in Markdown form. A real investigation would have actual `.eml` files captured via the Yahoo or Gmail provider and real PDFs in `documents/`. The pipeline accepts both.
- The clause-change-comparison report is meaningful only when document versions share enough structural overlap; in real use, name your document versions with the convention `name-v1.pdf`, `name-v2.pdf`, etc.
