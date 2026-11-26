"""SQLite schema and database access helpers."""
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY, transaction_ref TEXT NOT NULL UNIQUE,
 customer_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
 amount REAL NOT NULL CHECK(amount > 0), currency TEXT NOT NULL,
 source_file TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS watchlist (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
 reason TEXT NOT NULL, risk_weight INTEGER NOT NULL CHECK(risk_weight BETWEEN 1 AND 100)
);
CREATE TABLE IF NOT EXISTS screening_results (
 id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id),
 watchlist_id INTEGER REFERENCES watchlist(id), match_type TEXT NOT NULL,
 similarity REAL NOT NULL, risk_score INTEGER NOT NULL, risk_level TEXT NOT NULL,
 explanation TEXT NOT NULL, screened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_logs (
 event_id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
 details TEXT NOT NULL, previous_hash TEXT NOT NULL, current_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS processed_files (
 id INTEGER PRIMARY KEY, file_name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
 row_count INTEGER NOT NULL, processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_transactions_customer ON transactions(normalized_name);
CREATE INDEX IF NOT EXISTS idx_results_risk ON screening_results(risk_level);
CREATE INDEX IF NOT EXISTS idx_audit_hash ON audit_logs(current_hash);
"""

def connect(path: str = "data/watchlistguard.db") -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def initialize(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if absent."""
    conn.executescript(SCHEMA)
    conn.commit()

def seed_watchlist(conn: sqlite3.Connection) -> None:
    """Insert fictional entries without overwriting operator changes."""
    entries = [
        ("Amina Rahman", "amina rahman", "Synthetic high-risk test profile", 90),
        ("Victor Mensah", "victor mensah", "Synthetic sanctions-screening example", 85),
        ("Northstar Trading Ltd", "northstar trading ltd", "Synthetic entity example", 75),
    ]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO watchlist(name, normalized_name, reason, risk_weight) VALUES (?, ?, ?, ?)",
            entries,
        )
