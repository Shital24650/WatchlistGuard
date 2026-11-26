"""CSV ingestion with validation, deduplication and file fingerprints."""
import csv
import hashlib
import io
import sqlite3
from pathlib import Path
from typing import Optional
from .screening import normalize_name
from .audit import log_event

REQUIRED = {"transaction_ref", "customer_name", "amount", "currency"}


class IngestionError(ValueError):
    """Raised when an input CSV cannot be safely ingested."""


def ingest_csv(conn: sqlite3.Connection, path: str, source_name: Optional[str] = None) -> dict[str, int]:
    """Validate and ingest a CSV atomically; repeated file bytes are skipped."""
    file_path = Path(path)
    display_name = Path(source_name).name if source_name else file_path.name
    if not file_path.is_file():
        raise IngestionError(f"File not found: {path}")
    raw = file_path.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    if conn.execute("SELECT 1 FROM processed_files WHERE sha256 = ?", (fingerprint,)).fetchone():
        return {"inserted": 0, "rejected": 0, "duplicates": 0, "skipped_file": 1}
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames or not REQUIRED.issubset(set(reader.fieldnames)):
            raise IngestionError(f"CSV must contain columns: {', '.join(sorted(REQUIRED))}")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise IngestionError(f"Unable to read CSV: {exc}") from exc
    inserted = rejected = duplicates = 0
    with conn:
        for line_no, row in enumerate(rows, start=2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("record has missing or surplus columns")
                ref = (row.get("transaction_ref") or "").strip()
                name = (row.get("customer_name") or "").strip()
                currency = (row.get("currency") or "").strip().upper()
                amount_text = (row.get("amount") or "").strip()
                amount = float(amount_text)
                if not ref or not name or not currency or len(currency) != 3 or not (amount > 0 and amount < float("inf")):
                    raise ValueError("required value missing or amount/currency invalid")
            except (ValueError, TypeError):
                rejected += 1
                continue
            try:
                conn.execute(
                    """INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file)
                       VALUES(?,?,?,?,?,?)""",
                    (ref, name, normalize_name(name), amount, currency, display_name),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
        conn.execute(
            "INSERT INTO processed_files(file_name,sha256,row_count) VALUES(?,?,?)",
            (display_name, fingerprint, inserted),
        )
        log_event(
            conn, "INGEST",
            f"file={display_name}; inserted={inserted}; rejected={rejected}; duplicates={duplicates}",
        )
    return {"inserted": inserted, "rejected": rejected, "duplicates": duplicates, "skipped_file": 0}
