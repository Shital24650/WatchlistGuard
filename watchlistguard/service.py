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
    conditions = []
    parameters = []
    if risk_level is not None:
        conditions.append("COALESCE(s.risk_level, 'PENDING') = ?")
        parameters.append(risk_level)
    if screening_status == "PENDING":
        conditions.append("s.id IS NULL")
    elif screening_status == "SCREENED":
        conditions.append("s.id IS NOT NULL")
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(
        "SELECT COUNT(*) FROM transactions t "
        "LEFT JOIN screening_results s ON s.transaction_id=t.id" + where_sql,
        parameters,
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
                  COALESCE(s.risk_level,'PENDING') AS risk_level,
                  COALESCE(s.risk_score,0) AS risk_score,
                  COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
                  COALESCE(s.explanation,'Awaiting screening') AS explanation
           FROM transactions t
           LEFT JOIN screening_results s ON s.transaction_id=t.id"""
        + where_sql + " ORDER BY t.id ASC LIMIT ? OFFSET ?",
        parameters + [page_size, (page - 1) * page_size],
    ).fetchall()
    return total, rows
