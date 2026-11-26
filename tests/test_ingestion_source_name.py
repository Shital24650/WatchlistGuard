"""Regression test for the safe upload source label."""
import os
import tempfile
import unittest
from watchlistguard.db import connect, initialize, seed_watchlist
from watchlistguard.ingestion import ingest_csv


class IngestionSourceNameTests(unittest.TestCase):
    def test_supplied_source_name_is_used_in_database_and_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "random-upload-name.csv")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("transaction_ref,customer_name,amount,currency\nSRC1,Person,1,USD\n")
            conn = connect(":memory:")
            try:
                initialize(conn)
                seed_watchlist(conn)
                ingest_csv(conn, path, source_name="portfolio-sample.csv")
                self.assertEqual(conn.execute("SELECT source_file FROM transactions").fetchone()[0], "portfolio-sample.csv")
                self.assertEqual(conn.execute("SELECT file_name FROM processed_files").fetchone()[0], "portfolio-sample.csv")
                self.assertIn("portfolio-sample.csv", conn.execute("SELECT details FROM audit_logs").fetchone()[0])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
