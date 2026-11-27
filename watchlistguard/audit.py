"""Append-only SHA-256 hash-chain audit helpers."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from .db import dialect

GENESIS = "0" * 64

def _digest(event_id: int, timestamp: str, event_type: str, details: str, previous_hash: str) -> str:
    payload = json.dumps({"event_id": event_id, "timestamp": timestamp, "event_type": event_type,
                          "details": details, "previous_hash": previous_hash},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def log_event(conn: sqlite3.Connection, event_type: str, details: str) -> str:
    """Append one event, linking it to the preceding record hash."""
    # Every PostgreSQL audit writer takes the same transaction lock before
    # reading the chain head, preventing two writers from forking it.
    if dialect(conn) == "postgresql":
        conn.execute("SELECT pg_advisory_xact_lock(731942817)")
    elif not conn.in_transaction:
        # Acquire SQLite's write reservation before reading the chain head.
        # Otherwise concurrent deferred transactions can read the same head,
        # then race while upgrading to writers and fork or lose audit appends.
        conn.execute("BEGIN IMMEDIATE")
    previous = conn.execute("SELECT current_hash FROM audit_logs ORDER BY event_id DESC LIMIT 1").fetchone()
    prev_hash = previous[0] if previous else GENESIS
    timestamp = datetime.now(timezone.utc).isoformat()
    event_id = conn.execute("SELECT COALESCE(MAX(event_id), 0) + 1 FROM audit_logs").fetchone()[0]
    current = _digest(event_id, timestamp, event_type, details, prev_hash)
    conn.execute("INSERT INTO audit_logs(event_id,timestamp,event_type,details,previous_hash,current_hash) VALUES(?,?,?,?,?,?)",
                 (event_id, timestamp, event_type, details, prev_hash, current))
    return current

def verify_chain(conn: sqlite3.Connection) -> tuple[bool, str]:
    """Validate each record's digest and linkage, in event order."""
    previous = GENESIS
    rows = conn.execute("SELECT event_id,timestamp,event_type,details,previous_hash,current_hash FROM audit_logs ORDER BY event_id").fetchall()
    for row in rows:
        expected = _digest(row["event_id"], row["timestamp"], row["event_type"], row["details"], previous)
        if row["previous_hash"] != previous:
            return False, f"Event {row['event_id']}: previous-hash link mismatch"
        if row["current_hash"] != expected:
            return False, f"Event {row['event_id']}: current hash mismatch"
        previous = row["current_hash"]
    return True, f"Verified {len(rows)} audit event(s)."
