"""Unit tests use isolated in-memory databases and temporary CSV files."""
import csv
import os
import tempfile
import unittest
from watchlistguard.db import connect, initialize, seed_watchlist
from watchlistguard.ingestion import ingest_csv
from watchlistguard.screening import normalize_name, match_name, classify_risk
from watchlistguard.service import screen_pending
from watchlistguard.audit import log_event, verify_chain

class WatchlistGuardTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:"); initialize(self.conn); seed_watchlist(self.conn)
    def tearDown(self): self.conn.close()
    def make_csv(self, rows):
        temp = tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False, encoding="utf-8")
        writer = csv.DictWriter(temp, fieldnames=["transaction_ref","customer_name","amount","currency"])
        writer.writeheader(); writer.writerows(rows); temp.close(); self.addCleanup(lambda: os.unlink(temp.name))
        return temp.name
    def test_valid_and_invalid_csv_records(self):
        path = self.make_csv([
            {"transaction_ref":"A1","customer_name":"Amina Rahman","amount":"10","currency":"USD"},
            {"transaction_ref":"A2","customer_name":"Bad","amount":"-1","currency":"USD"},
            {"transaction_ref":"A3","customer_name":"No amount","amount":"oops","currency":"USD"}])
        result = ingest_csv(self.conn, path)
        self.assertEqual((result["inserted"], result["rejected"]), (1, 2))
    def test_duplicate_transaction_prevention(self):
        path = self.make_csv([{"transaction_ref":"D1","customer_name":"Person","amount":"1","currency":"USD"}])
        self.assertEqual(ingest_csv(self.conn, path)["inserted"], 1)
        self.assertEqual(ingest_csv(self.conn, path)["skipped_file"], 1)
        other = self.make_csv([{"transaction_ref":"D1","customer_name":"Person","amount":"2","currency":"USD"}])
        self.assertEqual(ingest_csv(self.conn, other)["duplicates"], 1)
    def test_exact_name_matching(self):
        self.assertEqual(match_name("Amina Rahman", "amina rahman")[0], "EXACT")
    def test_approximate_name_matching(self):
        kind, score = match_name("Amna Rahman", "Amina Rahman")
        self.assertEqual(kind, "APPROXIMATE"); self.assertGreaterEqual(score, .82)
    def test_risk_classification(self):
        self.assertEqual([classify_risk(x) for x in (20, 50, 90)], ["LOW","MEDIUM","HIGH"])
    def test_sql_injection_resistance(self):
        payload = "'; DROP TABLE watchlist; --"
        self.conn.execute("SELECT * FROM watchlist WHERE normalized_name = ?", (normalize_name(payload),))
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='watchlist'").fetchone())
    def test_audit_hash_verification(self):
        with self.conn: log_event(self.conn, "TEST", "first"); log_event(self.conn, "TEST", "second")
        self.assertTrue(verify_chain(self.conn)[0])
    def test_audit_tampering_detection(self):
        with self.conn: log_event(self.conn, "TEST", "original")
        self.conn.execute("UPDATE audit_logs SET details='changed' WHERE event_id=1"); self.conn.commit()
        self.assertFalse(verify_chain(self.conn)[0])
    def test_surplus_csv_columns_are_rejected(self):
        path = self.make_csv([{"transaction_ref":"EXTRA","customer_name":"Person","amount":"3","currency":"USD"}])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("EXTRA2,Person,4,USD,unexpected\n")
        result = ingest_csv(self.conn, path)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["rejected"], 1)
    def test_malformed_csv_quoting_is_reported(self):
        path = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        path.write('transaction_ref,customer_name,amount,currency\nBROKEN,"unterminated,1,USD')
        path.close()
        self.addCleanup(lambda: os.unlink(path.name))
        with self.assertRaises(ValueError):
            ingest_csv(self.conn, path.name)
    def test_missing_required_csv_header_is_rejected(self):
        temp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        temp.write("transaction_ref,customer_name,amount\nX1,Person,1\n")
        temp.close()
        self.addCleanup(lambda: os.unlink(temp.name))
        with self.assertRaises(ValueError):
            ingest_csv(self.conn, temp.name)
    def test_missing_csv_file_is_reported(self):
        with self.assertRaises(ValueError):
            ingest_csv(self.conn, "/tmp/watchlistguard-file-that-does-not-exist.csv")
    def test_non_finite_amounts_are_rejected(self):
        path = self.make_csv([
            {"transaction_ref":"NAN","customer_name":"Person","amount":"NaN","currency":"USD"},
            {"transaction_ref":"INF","customer_name":"Person","amount":"Infinity","currency":"USD"}])
        result = ingest_csv(self.conn, path)
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["rejected"], 2)
    def test_audit_record_deletion_is_detected(self):
        with self.conn:
            log_event(self.conn, "TEST", "first")
            log_event(self.conn, "TEST", "second")
        self.conn.execute("DELETE FROM audit_logs WHERE event_id=1")
        self.conn.commit()
        self.assertFalse(verify_chain(self.conn)[0])
    def test_screening_persists_result(self):
        path = self.make_csv([{"transaction_ref":"S1","customer_name":"Amina Rahman","amount":"10","currency":"USD"}])
        ingest_csv(self.conn, path); self.assertEqual(screen_pending(self.conn), 1)
        self.assertEqual(self.conn.execute("SELECT risk_level FROM screening_results").fetchone()[0], "HIGH")

if __name__ == "__main__": unittest.main()
