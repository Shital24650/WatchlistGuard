"""Opt-in tests. TEST_POSTGRES_URL must point to a disposable PostgreSQL DB."""
import os
import tempfile
import threading
import unittest
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

from watchlistguard.db import connect, close, initialize, seed_watchlist
from watchlistguard.ingestion import ingest_csv
from watchlistguard.service import screen_pending, report_page
from watchlistguard.audit import log_event, verify_chain

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")


@unittest.skipUnless(POSTGRES_URL, "NOT RUN: TEST_POSTGRES_URL disposable PostgreSQL unavailable")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["WATCHLISTGUARD_DATABASE_URL"] = POSTGRES_URL
        from alembic import command
        from alembic.config import Config
        config = Config("alembic.ini")
        command.upgrade(config, "head")

    def setUp(self):
        self.conn = connect()
        self.conn.execute("TRUNCATE audit_logs, screening_results, processed_files, transactions, watchlist RESTART IDENTITY CASCADE")
        self.conn.commit()
        initialize(self.conn)
        seed_watchlist(self.conn)

    def tearDown(self):
        if self.conn is not None:
            close(self.conn)

    def test_fresh_migration_and_transaction_ref_uniqueness(self):
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM watchlist LIMIT 1").fetchone())
        self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                          ("PG-SYN-1", "Test Name", "test name", 2, "USD", "synthetic.csv"))
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                              ("PG-SYN-1", "Other", "other", 3, "USD", "synthetic.csv"))
        self.conn.rollback()

    def test_ingestion_duplicate_screen_report_and_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "synthetic.csv"
            csv_path.write_text("transaction_ref,customer_name,amount,currency\nPG-SYN-2,Amina Rahman,10,USD\nPG-SYN-3,Jordan Lee,20,EUR\n")
            first = ingest_csv(self.conn, str(csv_path))
            again = ingest_csv(self.conn, str(csv_path))
            changed = Path(folder) / "changed.csv"
            changed.write_text("transaction_ref,customer_name,amount,currency\nPG-SYN-2,Changed Name,99,USD\nPG-SYN-4,New Person,4,GBP\n")
            duplicate_result = ingest_csv(self.conn, str(changed))
        self.assertEqual(first["inserted"], 2)
        self.assertEqual(again["skipped_file"], 1)
        self.assertEqual((duplicate_result["inserted"], duplicate_result["duplicates"]), (1, 1))
        self.assertEqual(screen_pending(self.conn), 3)
        total, rows = report_page(self.conn, page=1, page_size=1, screening_status="SCREENED")
        self.assertEqual((total, len(rows)), (3, 1))
        high_total, _ = report_page(self.conn, risk_level="HIGH")
        self.assertEqual(high_total, 1)
        with self.conn:
            log_event(self.conn, "PG_TEST", "synthetic")
        self.assertTrue(verify_chain(self.conn)[0])

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.conn:
                self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                                  ("PG-ROLLBACK", "Synthetic", "synthetic", 1, "USD", "test.csv"))
                raise RuntimeError("rollback check")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM transactions WHERE transaction_ref=?", ("PG-ROLLBACK",)).fetchone()[0], 0)

    def test_returning_lease_rolls_back_an_open_transaction(self):
        self.conn.execute("BEGIN")
        self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                          ("PG-LEASE-ROLLBACK", "Synthetic", "synthetic", 1, "USD", "test.csv"))
        close(self.conn)
        self.conn = None
        verifier = connect()
        try:
            self.assertEqual(verifier.execute("SELECT COUNT(*) FROM transactions WHERE transaction_ref=?",
                                              ("PG-LEASE-ROLLBACK",)).fetchone()[0], 0)
        finally:
            close(verifier)

    def test_screening_read_then_context_commits_results_and_audit_after_lease_return(self):
        self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                          ("PG-SCREEN-COMMIT", "Amina Rahman", "amina rahman", 10, "USD", "synthetic.csv"))
        self.conn.commit()
        # Reproduce the reviewed path: reads happen before screen_pending's
        # write context, then its pooled lease is returned before verification.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM screening_results").fetchone()[0], 0)
        self.assertEqual(screen_pending(self.conn), 1)
        close(self.conn)

        verifier = connect()
        try:
            self.assertEqual(verifier.execute("SELECT COUNT(*) FROM screening_results WHERE transaction_id=(SELECT id FROM transactions WHERE transaction_ref=?)",
                                              ("PG-SCREEN-COMMIT",)).fetchone()[0], 1)
            self.assertEqual(verifier.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type='SCREEN' AND details='screened=1'").fetchone()[0], 1)
            self.assertTrue(verify_chain(verifier)[0])
        finally:
            close(verifier)
        self.conn = None

    def test_screening_failure_rolls_back_results(self):
        self.conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                          ("PG-SCREEN-ROLLBACK", "Amina Rahman", "amina rahman", 10, "USD", "synthetic.csv"))
        self.conn.commit()
        with patch("watchlistguard.service.log_event", side_effect=RuntimeError("synthetic audit failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic audit failure"):
                screen_pending(self.conn)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM screening_results s JOIN transactions t ON t.id=s.transaction_id WHERE t.transaction_ref=?",
                                           ("PG-SCREEN-ROLLBACK",)).fetchone()[0], 0)

    def test_concurrent_transactions_and_audit_appends(self):
        errors = []

        def writer(i):
            try:
                conn = connect()
                try:
                    with conn:
                        conn.execute("INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) VALUES(?,?,?,?,?,?)",
                                     (f"PG-CONCURRENT-{i}", "Synthetic", "synthetic", i + 1, "USD", "test.csv"))
                        log_event(conn, "CONCURRENT_TEST", f"writer={i}")
                finally:
                    close(conn)
            except Exception as exc:
                errors.append(exc)

        workers = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
        self.assertFalse(errors, errors)
        self.assertTrue(verify_chain(self.conn)[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM transactions WHERE transaction_ref LIKE 'PG-CONCURRENT-%'").fetchone()[0], 6)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type='CONCURRENT_TEST'").fetchone()[0], 6)

    def test_concurrent_duplicate_file_submissions_are_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "same-upload.csv"
            csv_path.write_text(
                "transaction_ref,customer_name,amount,currency\nPG-DUPLICATE-SUBMIT,Synthetic Person,7,USD\n"
            )
            # Leave one lease available for this test case's fixture connection.
            barrier = threading.Barrier(4)

            def submit(_):
                conn = connect()
                try:
                    barrier.wait(timeout=5)
                    return ingest_csv(conn, str(csv_path))
                finally:
                    close(conn)

            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(submit, range(4)))
        self.assertEqual(sum(result["inserted"] for result in results), 1)
        self.assertEqual(sum(result["skipped_file"] for result in results), 3)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE transaction_ref=?", ("PG-DUPLICATE-SUBMIT",)
        ).fetchone()[0], 1)
        self.assertTrue(verify_chain(self.conn)[0])

    def test_report_indexes_match_filtered_report_query(self):
        indexes = {row[0] for row in self.conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename='screening_results'"
        ).fetchall()}
        self.assertIn("idx_results_risk_transaction", indexes)
        self.assertNotIn("idx_results_risk", indexes)

    def test_pool_exhaustion_times_out_and_recovers(self):
        with patch.dict(os.environ, {
            "WATCHLISTGUARD_DB_POOL_SIZE": "1",
            "WATCHLISTGUARD_DB_POOL_TIMEOUT": "0.2",
        }):
            parts = urlsplit(POSTGRES_URL)
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["application_name"] = "wg-pool-test-" + uuid.uuid4().hex
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            lease = connect(url)
            pool = lease.pool
            self.addCleanup(lambda: (self._forget_pool(url), pool.close()))
            try:
                from psycopg_pool import PoolTimeout
                with self.assertRaises(PoolTimeout):
                    connect(url)
            finally:
                close(lease)
            recovered = connect(url)
            try:
                self.assertEqual(recovered.execute("SELECT 1").fetchone()[0], 1)
            finally:
                close(recovered)

    @staticmethod
    def _forget_pool(url):
        from watchlistguard.db import _pools
        _pools.pop(url, None)

    def test_broken_lease_is_replaced_on_reconnect(self):
        broken = connect()
        broken.raw.close()
        with self.assertRaises(Exception):
            broken.execute("SELECT 1")
        close(broken)
        replacement = connect()
        try:
            self.assertEqual(replacement.execute("SELECT 1").fetchone()[0], 1)
        finally:
            close(replacement)


if __name__ == "__main__":
    unittest.main()
