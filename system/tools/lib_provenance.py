"""Shared provenance + audit-log helpers for the Paperline pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent   # system/tools/lib_provenance.py -> repo root
SYSTEM_DIR = REPO_ROOT / "system"
AUDIT_LOG_PATH = SYSTEM_DIR / "audit-log.log"
# Backwards-compat alias for any caller that still says META_DIR
META_DIR = SYSTEM_DIR
CORRESPONDENCE_DIR = REPO_ROOT / "correspondence"
DOCUMENTS_DIR = REPO_ROOT / "documents"
# CONTRACTS_DIR is an alias of DOCUMENTS_DIR. Some tools refer to a "contracts"
# folder; in paperline the same concept (versioned documents) lives under
# documents/. The alias keeps those tools working without a rename.
CONTRACTS_DIR = DOCUMENTS_DIR
MEMOS_DIR = REPO_ROOT / "memos"
FILINGS_DIR = REPO_ROOT / "filings"
CONTACTS_DIR = REPO_ROOT / "contacts"
REPORTS_DIR = REPO_ROOT / "reports"


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


@dataclass
class Source:
    system: str                                      # 'yahoo-mail', 'imported-from-existing', 'derived'
    thread_id: str | None = None
    message_id: str | None = None
    rfc822_message_id: str | None = None
    from_: str | None = None
    to: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    bcc: list = field(default_factory=list)
    subject: str | None = None
    sent_at_iso: str | None = None
    attachment_filename_as_sent: str | None = None
    source_path_if_imported: str | None = None    # for existing-folder imports

    def to_dict(self) -> dict:
        d = asdict(self)
        d["from"] = d.pop("from_")
        return {k: v for k, v in d.items() if v is not None and v != []}


@dataclass
class Retrieval:
    method: str                                      # 'browser-automation', 'imported-from-existing', 'derived'
    tool: str                                        # 'ba_click+download', 'pymupdf', 'tesseract+pdf2image'
    retrieved_at_iso: str
    operator: str = "agent"                          # generic default; callers should override with their actual operator id
    session_id: str | None = None
    # host defaults to "local" so the operator's hostname is not silently
    # written into every .provenance.json. Set PAPERLINE_RECORD_HOSTNAME=1 to
    # opt in to capturing the real hostname (useful for multi-machine setups).
    host: str = field(default_factory=lambda: socket.gethostname() if os.environ.get("PAPERLINE_RECORD_HOSTNAME") == "1" else "local")


@dataclass
class Provenance:
    artifact_path: str
    artifact_sha256: str
    artifact_size_bytes: int
    source: Source
    retrieval: Retrieval
    derived_from: str | None = None
    derivation_method: str | None = None
    ocr_used: bool = False
    errors: list = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "source": self.source.to_dict(),
            "retrieval": asdict(self.retrieval),
            "derived_from": self.derived_from,
            "derivation_method": self.derivation_method,
            "ocr_used": self.ocr_used,
            "errors": self.errors,
            "notes": self.notes,
        }

    def write_sidecar(self, sidecar_path: Path | None = None) -> Path:
        """Write {artifact}.provenance.json next to the artifact (or at sidecar_path)."""
        artifact = REPO_ROOT / self.artifact_path
        if sidecar_path is None:
            sidecar_path = artifact.parent / (artifact.name + ".provenance.json")
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return sidecar_path


def write_provenance_for_file(
    artifact_path: Path,
    source: Source,
    retrieval: Retrieval,
    derived_from: str | None = None,
    derivation_method: str | None = None,
    ocr_used: bool = False,
    errors: list | None = None,
    notes: str = "",
) -> Provenance:
    """Compute hash/size, build Provenance, write sidecar JSON, return the object."""
    sha = sha256_file(artifact_path)
    size = file_size(artifact_path)
    rel = str(artifact_path.relative_to(REPO_ROOT)).replace("\\", "/")
    p = Provenance(
        artifact_path=rel,
        artifact_sha256=sha,
        artifact_size_bytes=size,
        source=source,
        retrieval=retrieval,
        derived_from=derived_from,
        derivation_method=derivation_method,
        ocr_used=ocr_used,
        errors=errors or [],
        notes=notes,
    )
    p.write_sidecar()
    return p


def append_audit_log(
    event_type: str,
    artifact_path: Path | str,
    sha256: str | None = None,
    actor: str = "agent",
    notes: str = "",
) -> None:
    """Append a single line to audit-log.log. Never overwrites."""
    META_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(artifact_path, Path):
        try:
            artifact_path = str(artifact_path.relative_to(REPO_ROOT))
        except ValueError:
            artifact_path = str(artifact_path)
    artifact_path = str(artifact_path).replace("\\", "/")
    line = "\t".join([
        utcnow_iso(),
        event_type,
        artifact_path,
        sha256 or "-",
        actor,
        notes.replace("\t", " ").replace("\n", " "),
    ]) + "\n"
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def _append_log_line(
    log_path: Path,
    event_type: str,
    artifact_path: Path | str,
    sha256: str | None,
    actor: str,
    notes: str,
) -> None:
    """Internal: append one tab-delimited line to a log file. Never overwrites.

    Shared by append_audit_log, append_operations_log, and
    append_chain_of_custody — they differ only in which log file they target.
    All three are append-only and tamper-evident via the per-line sha256.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(artifact_path, Path):
        try:
            artifact_path = str(artifact_path.relative_to(REPO_ROOT))
        except ValueError:
            artifact_path = str(artifact_path)
    artifact_path = str(artifact_path).replace("\\", "/")
    line = "\t".join([
        utcnow_iso(),
        event_type,
        artifact_path,
        sha256 or "-",
        actor,
        notes.replace("\t", " ").replace("\n", " "),
    ]) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def append_operations_log(
    event_type: str,
    artifact_path: Path | str,
    log_path: Path | str | None = None,
    actor: str = "agent",
    sha256: str | None = None,
    notes: str = "",
) -> None:
    """Append a line to an operations log — engineering bookkeeping only.
    Used by the journal and reference subsystems.

    `log_path` lets each subsystem target its own operations log
    (journal-operations.log, reference-operations.log). When omitted, defaults
    to system/operations-log.log.
    """
    target = Path(log_path) if log_path else (SYSTEM_DIR / "operations-log.log")
    _append_log_line(target, event_type, artifact_path, sha256, actor, notes)


def append_chain_of_custody(
    event_type: str,
    artifact_path: Path | str,
    sha256: str | None = None,
    actor: str = "agent",
    notes: str = "",
) -> None:
    """Append a line to system/chain-of-custody.log — the record-integrity
    audit trail for the evidence corpus. Distinct from the operations log
    (engineering bookkeeping) and from audit-log.log.
    """
    _append_log_line(
        SYSTEM_DIR / "chain-of-custody.log",
        event_type, artifact_path, sha256, actor, notes,
    )


def load_provenance(artifact_path: Path) -> dict | None:
    sidecar = artifact_path.parent / (artifact_path.name + ".provenance.json")
    if not sidecar.exists():
        return None
    with open(sidecar, encoding="utf-8") as f:
        return json.load(f)


def safe_slug(text: str, maxlen: int = 60) -> str:
    """ASCII-safe slug for filenames; preserves alphanumerics, replaces others with '-'."""
    if not text:
        return "untitled"
    out = []
    last_dash = False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        elif ch in (" ", "_", "-", ".", "/"):
            if not last_dash:
                out.append("-")
                last_dash = True
        # drop everything else
    s = "".join(out).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rstrip("-")
    return s or "untitled"


if __name__ == "__main__":
    # quick self-test
    print(f"REPO_ROOT={REPO_ROOT}")
    print(f"AUDIT_LOG_PATH={AUDIT_LOG_PATH}")
    print(f"utcnow={utcnow_iso()}")
    print(f"slug 'Re: Example Subject -- items to reconcile' = {safe_slug('Re: Example Subject -- items to reconcile')}")
