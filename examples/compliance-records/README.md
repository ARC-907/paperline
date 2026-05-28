# Compliance Records — Worked Example

Smaller-scale example demonstrating Paperline applied to a small-org compliance / regulatory-records workflow. Buyer: compliance officer at a startup, non-profit, or SMB regulated by GDPR / CCPA / HIPAA-light / industry-specific rules.

The scenario: a fictional company ("Example Co.") receives a regulatory inquiry about its data-handling practices. The compliance officer is building a verifiable record of internal communications, vendor correspondence, and the policy document revisions that the regulator may want to inspect.

All names, dates, and entities are FICTIONAL.

## Files in this example

- `project-config.json` — tuned for the compliance scenario
- `correspondence/2026-02-15/m001/` — 1 email: regulator inquiry forwarded internally
- `documents/data-policy-v1.pdf.md` — policy version pre-inquiry
- `documents/data-policy-v2.pdf.md` — policy revised in response to inquiry (clause-diff target)
- `contacts/regulator.md` — external regulator contact canon
- `contacts/internal-compliance-lead.md` — internal lead contact canon

## What this demonstrates

- Hash-verified policy version chain (regulator can verify the document they received matches the bytes on the company's archive)
- Audit-log + manifest format suitable for compliance evidence
- The records-vs-synthesis boundary that compliance frameworks expect (originals + audit trail separate from analysis / response)
- Self-hosted operation — no cloud-vendor data-residency concerns

## Adapting to your own compliance program

1. Replace `contacts[]` in `project-config.json` with your regulator + your internal team
2. Replace `scope_rules` to match your regulator's email domain + policy-document keywords
3. Drop your own correspondence into `correspondence/`
4. Drop your policy versions into `documents/`
5. Run `./run_pipeline.sh`

The reports give you a regulator-ready audit trail without a GRC platform.

## What this example does NOT demonstrate

- Multi-jurisdiction (GDPR + CCPA + HIPAA) cross-referencing (would require a richer contact + scope model)
- Workflow approval routing (Paperline is records-focused, not workflow-focused — pair with your existing approval tool)
- Encryption-at-rest (planned for v1.1)

For the journalism investigation analog, see `../journalism-investigation/`.
