# documents/

Per-document-family, per-version folders. Each document version gets its own folder under its family:

```text
documents/<doc-family>/v<NN>_<YYYY-MM-DD>/
  contract.pdf       the actual document binary (filename kept stable across kit versions)
  contract.txt       text mirror
  decomposed.json    section-by-section decomposition with stable section IDs
  delivered-by.md    wikilink back to the source message (or note for baselines)
  manifest.json      sha256 + size
```

`<doc-family>` is a kebab-case slug grouping related versions of the same document (e.g. `vendor-msa`, `service-agreement`, `nda-template`). All versions within a family share the same `decomposed.json` schema so `diff_contracts.py` can compare them section-by-section.

When a document first arrives as an email attachment, the email's `attachments/` folder should contain a `.pointer.md` referencing the canonical version here (not a duplicated binary). That keeps the per-binary sha256 chain unambiguous.
