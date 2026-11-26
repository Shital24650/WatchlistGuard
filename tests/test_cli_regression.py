"""CLI regression tests use a fresh temporary SQLite database."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WatchlistGuardCliRegressionTests(unittest.TestCase):
    def test_ingest_screen_report_and_audit_verify(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = os.path.join(folder, "cli-regression.sqlite3")
            csv_path = os.path.join(folder, "synthetic.csv")
            Path(csv_path).write_text(
                "transaction_ref,customer_name,amount,currency\n"
                "CLI-SYN-1,Amina Rahman,10,USD\n"
                "CLI-SYN-2,Jordan Lee,20,INR\n",
                encoding="utf-8",
            )

            def run(*args):
                return subprocess.run(
                    [sys.executable, "main.py", "--db", db_path, *args],
                    cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
                )

            ingest = run("ingest", csv_path)
            self.assertEqual(ingest.returncode, 0, ingest.stderr)
            self.assertIn("inserted=2", ingest.stdout)
            repeated = run("ingest", csv_path)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("skipped_file=1", repeated.stdout)
            screen = run("screen")
            self.assertEqual(screen.returncode, 0, screen.stderr)
            self.assertIn("Screened 2 pending", screen.stdout)
            report = run("report")
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("CLI-SYN-1", report.stdout)
            self.assertIn("Total: 2 transaction(s).", report.stdout)
            audit = run("audit-verify")
            self.assertEqual(audit.returncode, 0, audit.stderr)
            self.assertIn("Verified", audit.stdout)


if __name__ == "__main__":
    unittest.main()
