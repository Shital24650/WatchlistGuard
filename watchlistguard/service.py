"""Application use cases."""
import sqlite3
from .db import seed_watchlist
from .audit import log_event
from .screening import assess_name

def screen_pending(conn: sqlite3.Connection) -> int:
    """Screen transactions without an existing result in one DB transaction."""
    seed_watchlist(conn)
    entries = conn.execute("SELECT id,name,normalized_name,reason,risk_weight FROM watchlist ORDER BY id").fetchall()
    pending = conn.execute("""SELECT t.id,t.customer_name FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id
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
    screened_risk = risk_level is not None and risk_level != "PENDING"
    if screened_risk and screening_status == "PENDING":
        return 0, []
    if risk_level == "PENDING" and screening_status == "SCREENED":
        return 0, []
    if screened_risk:
        filter_sql = " FROM screening_results s JOIN transactions t ON t.id=s.transaction_id"
        predicates = ["s.risk_level = ?"]
        parameters = [risk_level]
    else:
        filter_sql = " FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id"
        predicates = []
        parameters = []
        if risk_level == "PENDING" or screening_status == "PENDING":
            predicates.append("s.id IS NULL")
        if screening_status == "SCREENED":
            predicates.append("s.id IS NOT NULL")
    if predicates:
        filter_sql += " WHERE " + " AND ".join(predicates)
    count_sql = "SELECT COUNT(*)" + filter_sql
    total = conn.execute(count_sql, parameters).fetchone()[0]
    page_sql = """SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
                  COALESCE(s.risk_level,'PENDING') AS risk_level,
                  COALESCE(s.risk_score,0) AS risk_score,
                  COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
                  COALESCE(s.explanation,'Awaiting screening') AS explanation
           """ + filter_sql + (" ORDER BY s.transaction_id ASC" if screened_risk else " ORDER BY t.id ASC") + " LIMIT ? OFFSET ?"
    rows = conn.execute(page_sql, parameters + [page_size, (page - 1) * page_size]).fetchall()
    return total, rows


def report_cursor(conn, after_id=0, page_size=20, risk_level=None, screening_status=None):
    """Fetch the next bounded report slice without a count or deep OFFSET."""
    screened_risk = risk_level is not None and risk_level != "PENDING"
    if screened_risk and screening_status == "PENDING":
        return [], False, None
    if risk_level == "PENDING" and screening_status == "SCREENED":
        return [], False, None
    predicates = ["t.id > ?"]
    parameters = [after_id]
    if screened_risk:
        from_sql = " FROM screening_results s JOIN transactions t ON t.id=s.transaction_id"
        predicates.append("s.risk_level = ?")
        parameters.append(risk_level)
        order_by = "s.transaction_id"
    else:
        from_sql = " FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id"
        if risk_level == "PENDING" or screening_status == "PENDING":
            predicates.append("s.id IS NULL")
        if screening_status == "SCREENED":
            predicates.append("s.id IS NOT NULL")
        order_by = "t.id"
    sql = """SELECT t.id AS cursor_id,t.transaction_ref,t.customer_name,t.amount,t.currency,
        COALESCE(s.risk_level,'PENDING') AS risk_level,
        COALESCE(s.risk_score,0) AS risk_score,
        COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
        COALESCE(s.explanation,'Awaiting screening') AS explanation
        """ + from_sql + " WHERE " + " AND ".join(predicates) + " ORDER BY " + order_by + " ASC LIMIT ?"
    fetched = conn.execute(sql, parameters + [page_size + 1]).fetchall()
    has_more = len(fetched) > page_size
    rows = fetched[:page_size]
    next_after_id = rows[-1]["cursor_id"] if has_more and rows else None
    public_rows = []
    for row in rows:
        item = dict(row)
        item.pop("cursor_id", None)
        public_rows.append(item)
    return public_rows, has_more, next_after_id
