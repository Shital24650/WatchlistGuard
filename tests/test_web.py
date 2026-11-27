"""Endpoint tests for the Flask demo dashboard."""
import io
import os
import tempfile
import unittest

from app import create_app
from tests.security_client import sign_in_admin

VALID_CSV = (b"transaction_ref,customer_name,amount,currency\n"
             b"WEB-001,Amina Rahman,125.50,USD\n"
             b"WEB-002,Jordan Lee,20,INR\n")


class WatchlistGuardWebTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.temp_dir.name, "web-test.db")
        self.app = create_app({"TESTING": True, "DATABASE": db_path, "SECRET_KEY": "test-only"})
        self.client = sign_in_admin(self.app, db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload(self, filename="transactions.csv", data=VALID_CSV):
        return self.client.post(
            "/upload", data={"file": (io.BytesIO(data), filename)},
            content_type="multipart/form-data", follow_redirects=True,
        )

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_dashboard_renders_summary_and_demo_warning(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Screening overview", response.data)
        self.assertIn(b"DEMO ONLY", response.data)
        self.assertIn(b"TOTAL TRANSACTIONS", response.data)

    def test_csv_upload_and_report_display(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"inserted=2", response.data)
        self.assertIn(b"WEB-001", response.data)
        self.assertIn(b"NOT_SCREENED", response.data)

    def test_screening_action_updates_results(self):
        self.upload()
        response = self.client.post("/screen", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Screening completed", response.data)
        self.assertIn(b"WEB-001", response.data)
        self.assertIn(b"EXACT", response.data)
        self.assertIn(b"HIGH", response.data)

    def test_audit_verification_action(self):
        self.upload()
        response = self.client.post("/audit/verify", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Verified", response.data)
        self.assertIn(b"AUDIT_VERIFY", response.data)

    def test_invalid_extension_is_rejected(self):
        response = self.upload("transactions.txt", VALID_CSV)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Only files with a .csv extension", response.data)
        self.assertNotIn(b"WEB-001", response.data)

    def test_malformed_csv_is_rejected_without_stack_trace(self):
        malformed = b'transaction_ref,customer_name,amount,currency\nBAD,"unterminated,1,USD'
        response = self.upload(data=malformed)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"could not be processed", response.data)
        self.assertNotIn(b"Traceback", response.data)

    def test_missing_required_columns_are_rejected(self):
        response = self.upload(data=b"transaction_ref,customer_name,amount\nX,Name,1\n")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"could not be processed", response.data)

    def test_empty_upload_is_rejected(self):
        response = self.upload(data=b"")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"file is empty", response.data)

    def test_upload_over_limit_is_rejected(self):
        response = self.upload(data=b"x" * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"1 MB or smaller", response.data)

    def test_dashboard_escapes_uploaded_customer_markup(self):
        payload = b"transaction_ref,customer_name,amount,currency\nXSS-1,<script>alert(1)</script>,1,USD\n"
        response = self.upload(data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)
        self.assertIn(b"&lt;script&gt;", response.data)


if __name__ == "__main__":
    unittest.main()
