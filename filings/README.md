# filings/

One folder per FILED submission — anything you formally submitted to a third party that gets a tracking number, ticket ID, or confirmation receipt. Organized by recipient:

```text
filings/<RECIPIENT>/<YYYY-MM-DD>_<slug>/
  filing.pdf or .md          the submission text
  exhibits/                  numbered exhibits (or 01_*, 02_*, ... in the same folder)
  confirmation.{pdf,md,png}  filing confirmation from the recipient
  manifest.json              sha256 + size + submission metadata
```

Examples of recipient folders you might create (depending on the project):

- `BBB/` — Better Business Bureau
- `Vendor-Support/` — formal support tickets to vendors
- `City/` — city-permit-office submissions
- `Insurance/` — insurance claim filings
- `Records-Request/` — formal records or information requests
- Other regulators or formal channels relevant to your project

**Only filed material belongs here.** Drafts and unfiled submissions belong in `system/` or `reports/strategy/`.
