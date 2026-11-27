"""Compare the legacy and optimized report query on a reproducible SQLite set."""
import argparse
import statistics
import tempfile
import time
from pathlib import Path

from watchlistguard.db import close, connect, initialize
from watchlistguard.service import report_cursor, report_page

ROWS = 50_000
WARMUPS = 5
SAMPLES = 40
DEEP_PAGE = 100
PAGE_SIZE = 20
OLD_FILTER = """ FROM transactions t LEFT JOIN screening_results s ON s.transaction_id=t.id
WHERE (CAST(? AS TEXT) IS NULL OR COALESCE(s.risk_level, 'PENDING') = ?)
AND (CAST(? AS TEXT) IS NULL OR (? = 'PENDING' AND s.id IS NULL)
OR (? = 'SCREENED' AND s.id IS NOT NULL))"""
OLD_PARAMS = ("HIGH", "HIGH", None, None, None)
OLD_COUNT = "SELECT COUNT(*)" + OLD_FILTER
OLD_PAGE = """SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
COALESCE(s.risk_level,'PENDING') AS risk_level,COALESCE(s.risk_score,0) AS risk_score,
COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
COALESCE(s.explanation,'Awaiting screening') AS explanation""" + OLD_FILTER + " ORDER BY t.id ASC LIMIT ? OFFSET ?"


def _percentile(values, percentile):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))]


def _measure(callback):
    for _ in range(WARMUPS):
        callback()
    samples = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        callback()
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "p99_ms": round(_percentile(samples, 0.99), 3),
        "samples": SAMPLES,
    }


def _legacy_page(conn):
    count = conn.execute(OLD_COUNT, OLD_PARAMS).fetchone()[0]
    rows = conn.execute(OLD_PAGE, OLD_PARAMS + (20, 0)).fetchall()
    return count, [dict(row) for row in rows]


def run(rows=ROWS):
    with tempfile.TemporaryDirectory(prefix="watchlistguard-benchmark-") as folder:
        conn = connect(str(Path(folder) / "benchmark.sqlite3"))
        try:
            initialize(conn)
            with conn:
                conn.executemany(
                    "INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) "
                    "VALUES(?,?,?,?,?,?)",
                    ((f"BENCH-{i}", f"Synthetic Customer {i}", f"synthetic customer {i}", 12.5, "USD", "benchmark.csv")
                     for i in range(rows)),
                )
                conn.executemany(
                    "INSERT INTO screening_results(transaction_id,watchlist_id,match_type,similarity,risk_score,risk_level,explanation) "
                    "VALUES(?,NULL,'NONE',0,0,?, 'synthetic benchmark row')",
                    ((i, "HIGH" if i % 20 == 1 else "LOW") for i in range(1, rows + 1) if i % 10 != 0),
                )

            conn.execute("DROP INDEX idx_results_risk_transaction")
            conn.execute("CREATE INDEX idx_results_risk ON screening_results(risk_level)")
            conn.commit()
            legacy_count_plan = conn.execute("EXPLAIN QUERY PLAN " + OLD_COUNT, OLD_PARAMS).fetchall()
            legacy = _measure(lambda: _legacy_page(conn))
            legacy_result = _legacy_page(conn)
            deep_offset = (DEEP_PAGE - 1) * PAGE_SIZE
            legacy_deep = _measure(lambda: (
                conn.execute(OLD_COUNT, OLD_PARAMS).fetchone(),
                conn.execute(OLD_PAGE, OLD_PARAMS + (PAGE_SIZE, deep_offset)).fetchall(),
            ))

            conn.execute("DROP INDEX idx_results_risk")
            conn.execute(
                "CREATE INDEX idx_results_risk_transaction ON screening_results(risk_level, transaction_id)"
            )
            conn.commit()
            optimized_count_plan = conn.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM transactions t "
                "LEFT JOIN screening_results s ON s.transaction_id=t.id WHERE s.risk_level=?",
                ("HIGH",),
            ).fetchall()
            optimized_page_sql = """SELECT t.transaction_ref,t.customer_name,t.amount,t.currency,
                COALESCE(s.risk_level,'PENDING') AS risk_level,COALESCE(s.risk_score,0) AS risk_score,
                COALESCE(s.match_type,'NOT_SCREENED') AS match_type,
                COALESCE(s.explanation,'Awaiting screening') AS explanation
                FROM screening_results s JOIN transactions t ON t.id=s.transaction_id
                WHERE s.risk_level=? ORDER BY s.transaction_id ASC LIMIT ? OFFSET ?"""
            optimized_page_params = ("HIGH", PAGE_SIZE, 0)
            optimized_page_plan = conn.execute(
                "EXPLAIN QUERY PLAN " + optimized_page_sql, optimized_page_params,
            ).fetchall()
            optimized_count_only = _measure(lambda: conn.execute(
                "SELECT COUNT(*) FROM screening_results WHERE risk_level=?", ("HIGH",)
            ).fetchone())
            optimized_page_only = _measure(lambda: conn.execute(
                optimized_page_sql, optimized_page_params,
            ).fetchall())
            optimized = _measure(lambda: report_page(conn, page=1, page_size=20, risk_level="HIGH"))
            optimized_result = report_page(conn, page=1, page_size=20, risk_level="HIGH")
            compatible_result = (optimized_result[0], [dict(row) for row in optimized_result[1]])
            if legacy_result != compatible_result:
                raise AssertionError("Optimized report query changed report results")
            cursor_after_id = 20 * deep_offset
            cursor_deep = _measure(lambda: report_cursor(
                conn, after_id=cursor_after_id, page_size=PAGE_SIZE, risk_level="HIGH",
            ))
            old_deep_rows = conn.execute(
                OLD_PAGE, OLD_PARAMS + (PAGE_SIZE, deep_offset),
            ).fetchall()
            cursor_rows, _, _ = report_cursor(
                conn, after_id=cursor_after_id, page_size=PAGE_SIZE, risk_level="HIGH",
            )
            if [dict(row) for row in old_deep_rows] != cursor_rows:
                raise AssertionError("Cursor page does not match the equivalent legacy deep-offset page")

            return {
                "database": "SQLite",
                "dataset_transactions": rows,
                "dataset_screened": rows - (rows // 10),
                "filter": "risk_level=HIGH",
                "page": 1,
                "page_size": PAGE_SIZE,
                "warmups": WARMUPS,
                "legacy": legacy,
                "optimized": optimized,
                "deep_page": DEEP_PAGE,
                "legacy_deep_offset": legacy_deep,
                "cursor_deep_page": cursor_deep,
                "legacy_count_plan": [row[3] for row in legacy_count_plan],
                "optimized_count_plan": [row[3] for row in optimized_count_plan],
                "optimized_page_plan": [row[3] for row in optimized_page_plan],
                "optimized_count_only": optimized_count_only,
                "optimized_page_only": optimized_page_only,
            }
        finally:
            close(conn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=ROWS)
    print(run(parser.parse_args().rows))
