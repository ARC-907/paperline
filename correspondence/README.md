# correspondence/

Per-date, per-message folders. Each email gets one folder named `<HHMM>_<subject-slug>/` containing:

- `original.eml` — the pristine RFC822 email (write-once)
- `transcript.md` — human-readable Markdown rendering
- `headers.json` — parsed RFC822 metadata
- `manifest.json` — sha256 + size for every file in the folder
- `attachments/<name>.{pdf,docx,...}` — binary attachments (or `.pointer.md` if the attachment is a document or memo living elsewhere)
- `attachments/<name>.txt` — text mirror of the binary

See [SCHEMA.md](../SCHEMA.md) for the manifest format and [examples/](../examples/) for a populated example.
