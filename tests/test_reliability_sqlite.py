"""SQLite concurrency and failure regression tests use disposable databases."""
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from watchlistguard.audit import log_event, verify_chain
from watchlistguard.db import close, connect, initialize
from watchlistguard.ingestion import ingest_csv


class SQLiteReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "concurrency.sqlite3")
        conn = connect(self.db_path)
        initialize(conn)
        close(conn)

    def tearDown(self):
        self.temp.cleanup()

    def _parallel(self, count, operation):
        barrier = threading.Barrier(count)

        def run(index):
            barrier.wait(timeout=5)
            return operation(index)

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(run, range(count)))

    def test_concurrent_distinct_files_with_duplicate_refs_insert_once(self):
        files = []
        for index in range(8):
            path = Path(self.temp.name) / f"batch-{index}.csv"
            path.write_text(
                "transaction_ref,customer_name,amount,currency\n"
                f"SHARED-REF,Customer {index},10,USD\n"
                f"UNIQUE-{index},Customer {index},12,EUR\n",
                encoding="utf-8",
            )
            files.append(path)

        def ingest(index):
            conn = connect(self.db_path)
            try:
                return ingest_csv(conn, str(files[index]))
            finally:
                close(conn)

        results = self._parallel(len(files), ingest)
        self.assertEqual(sum(result["inserted"] for result in results), 9)
        self.assertEqual(sum(result["duplicates"] for result in results), 7)
        check = connect(self.db_path)
        try:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 9)
            self.assertTrue(verify_chain(check)[0])
        finally:
            close(check)

    def test_concurrent_audit_appends_preserve_a_single_hash_chain(self):
        def append(index):
            conn = connect(self.db_path)
            try:
                with conn:
                    log_event(conn, "SQLITE_CONCURRENT_TEST", f"writer={index}")
            finally:
                close(conn)

        self._parallel(12, append)
        check = connect(self.db_path)
        try:
            self.assertEqual(check.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE event_type=?", ("SQLITE_CONCURRENT_TEST",)
            ).fetchone()[0], 12)
            self.assertEqual(verify_chain(check)[0], True)
        finally:
            close(check)

    def test_sqlite_initialize_replaces_unused_legacy_indexes(self):
        conn = connect(self.db_path)
        try:
            conn.execute("DROP INDEX idx_results_risk_transaction")
            conn.executescript(
                "CREATE INDEX idx_transactions_customer ON transactions(normalized_name);"
                "CREATE INDEX idx_transactions_created ON transactions(created_at);"
                "CREATE INDEX idx_results_risk ON screening_results(risk_level);"
                "CREATE INDEX idx_audit_hash ON audit_logs(current_hash);"
            )
            initialize(conn)
            indexes = {row[1] for row in conn.execute("PRAGMA index_list('screening_results')").fetchall()}
            tx_indexes = {row[1] for row in conn.execute("PRAGMA index_list('transactions')").fetchall()}
            audit_indexes = {row[1] for row in conn.execute("PRAGMA index_list('audit_logs')").fetchall()}
            self.assertIn("idx_results_risk_transaction", indexes)
            self.assertNotIn("idx_results_risk", indexes)
            self.assertNotIn("idx_transactions_customer", tx_indexes)
            self.assertNotIn("idx_transactions_created", tx_indexes)
            self.assertNotIn("idx_audit_hash", audit_indexes)
        finally:
            close(conn)


if __name__ == "__main__":
    unittest.main()
