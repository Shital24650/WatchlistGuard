"""Application use cases."""
import sqlite3
from .db import seed_watchlist
from .audit import log_event
from .screening import assess_name

def screen_pending(conn: sqlite3.Connection) -> int:
    """Screen transactions without an existing result in one DB transaction."""
    seed_watchlist(conn)
    entries = conn.execute("SELECT id,name,normalized_name,reason,risk_weight FROM watchlist ORDER BY id").fetchall()
    pending = conn.execute("""SELECT t.* FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id
                              WHERE s.id IS NULL ORDER BY t.id""").fetchall()
    with conn:
        for tx in pending:
            result = assess_name(tx["customer_name"], entries)
            conn.execute("""INSERT INTO screening_results(transaction_id,watchlist_id,match_type,similarity,risk_score,risk_level,explanation)
                            VALUES(?,?,?,?,?,?,?)""",
                         (tx["id"], result["watchlist_id"], result["match_type"], result["similarity"],
                          result["risk_score"], result["risk_level"], result["explanation"]))
        log_event(conn, "SCREEN", f"screened={len(pending)}")
    return len(pending)

def report_rows(conn: sqlite3.Connection):
    """Return latest screening report rows, including unmatched transactions."""
    return conn.execute("""SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
        COALESCE(s.risk_level,'PENDING') AS risk_level,COALESCE(s.risk_score,0) AS risk_score,
        COALESCE(s.match_type,'NOT_SCREENED') AS match_type,COALESCE(s.explanation,'Awaiting screening') AS explanation
        FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id ORDER BY t.id""").fetchall()


def report_page(conn, page=1, page_size=20, risk_level=None, screening_status=None):
    """Return matching report rows with deterministic SQL-level pagination."""
    filter_sql = """ FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id
        WHERE (CAST(? AS TEXT) IS NULL OR COALESCE(s.risk_level, 'PENDING') = ?)
          AND (CAST(? AS TEXT) IS NULL OR (? = 'PENDING' AND s.id IS NULL)
                        OR (? = 'SCREENED' AND s.id IS NOT NULL))"""
    parameters = [risk_level, risk_level, screening_status, screening_status, screening_status]
    count_sql = "SELECT COUNT(*)" + filter_sql
    total = conn.execute(
        count_sql,
        parameters,
    ).fetchone()[0]
    page_sql = """SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
                  COALESCE(s.risk_level,'PENDING') AS risk_level,
                  COALESCE(s.risk_score,0) AS risk_score,
                  COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
                  COALESCE(s.explanation,'Awaiting screening') AS explanation
           """ + filter_sql + " ORDER BY t.id ASC LIMIT ? OFFSET ?"
    rows = conn.execute(
        page_sql,
        parameters + [page_size, (page - 1) * page_size],
    ).fetchall()
    return total, rows
