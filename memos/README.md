# memos/

Per-memo folders for free-standing communications that aren't versioned documents — letters, statements, notes that you sent or received as a message body or attachment.

- `memos/from-user/<YYYY-MM-DD>_<slug>/` — memos sent BY the project's user (you / the operator)
- `memos/from-other-party/<YYYY-MM-DD>_<slug>/` — memos sent BY any other party

Each memo folder contains:

- `memo.{pdf,docx,md}` — the binary or markdown form of the memo
- `memo.txt` — text mirror
- `delivered-by.md` — wikilink to the source message OR a note that the memo was sent outside the captured corpus
- `manifest.json` — sha256 + size

When a memo first arrives as an email attachment, the email's `attachments/` folder should contain a `.pointer.md` referencing the canonical memo here.
