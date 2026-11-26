"""Flask API integration tests use isolated temporary SQLite databases."""
import io
import os
import tempfile
import unittest

from app import create_app
from watchlistguard.audit import log_event
from watchlistguard.db import connect, initialize

VALID_CSV = (
    b"transaction_ref,customer_name,amount,currency\n"
    b"API-001,Amina Rahman,125.50,USD\n"
    b"API-002,Jordan Lee,20,INR\n"
)


class WatchlistGuardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "api-test.sqlite3")
        self.app = create_app({
            "TESTING": True,
            "DATABASE": self.db_path,
            "SECRET_KEY": "test-only-secret",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload(self, filename="transactions.csv", data=VALID_CSV):
        return self.client.post(
            "/api/upload",
            data={"file": (io.BytesIO(data), filename)},
            content_type="multipart/form-data",
        )

    def test_health_uses_test_database(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        self.assertTrue(os.path.exists(self.db_path))

    def test_upload_and_report(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["inserted"], 2)
        report = self.client.get("/api/report")
        self.assertEqual(report.status_code, 200)
        payload = report.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["results"][0]["transaction_ref"], "API-001")
        self.assertEqual(payload["results"][0]["risk_level"], "PENDING")

    def test_missing_upload_file_is_bad_request(self):
        response = self.client.post("/api/upload")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_invalid_extension_is_bad_request(self):
        response = self.upload("transactions.txt")
        self.assertEqual(response.status_code, 400)
        self.assertIn(".csv", response.get_json()["error"])

    def test_empty_csv_is_bad_request(self):
        response = self.upload(data=b"")
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.get_json()["error"])

    def test_missing_required_columns_is_bad_request(self):
        response = self.upload(data=b"transaction_ref,customer_name,amount\nX,Name,1\n")
        self.assertEqual(response.status_code, 400)
        self.assertIn("required columns", response.get_json()["error"])

    def test_malformed_csv_is_bad_request(self):
        response = self.upload(data=b'transaction_ref,customer_name,amount,currency\nX,"bad,1,USD')
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be processed", response.get_json()["error"])

    def test_upload_over_limit_is_payload_too_large(self):
        response = self.upload(data=b"x" * (1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)
        self.assertIn("1 MB", response.get_json()["error"])

    def test_screening_persists_results(self):
        self.assertEqual(self.upload().status_code, 200)
        response = self.client.post("/api/screen")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["screened"], 2)
        report = self.client.get("/api/report").get_json()
        self.assertEqual(report["results"][0]["risk_level"], "HIGH")

    def test_screening_second_run_is_idempotent(self):
        self.upload()
        self.assertEqual(self.client.post("/api/screen").get_json()["screened"], 2)
        self.assertEqual(self.client.post("/api/screen").get_json()["screened"], 0)

    def test_audit_verification_records_event(self):
        self.upload()
        response = self.client.post("/api/audit/verify")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["valid"])
        self.assertIn("Verified", response.get_json()["message"])
        self.assertEqual(self.client.get("/api/report").status_code, 200)

    def test_audit_tampering_returns_conflict(self):
        self.upload()
        conn = connect(self.db_path)
        try:
            with conn:
                log_event(conn, "TEST", "original")
            conn.execute("UPDATE audit_logs SET details='tampered' WHERE event_type='TEST'")
            conn.commit()
        finally:
            conn.close()
        response = self.client.post("/api/audit/verify")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.get_json()["valid"])

    def test_openapi_json_is_valid_and_matches_api_routes(self):
        response = self.client.get("/api/openapi.json")
        self.assertEqual(response.status_code, 200)
        spec = response.get_json()
        self.assertEqual(spec["openapi"], "3.0.3")
        for path in ("/health", "/api/openapi.json", "/api/docs", "/api/upload",
                     "/api/screen", "/api/report", "/api/audit/verify"):
            self.assertIn(path, spec["paths"])
        self.assertEqual(spec["paths"]["/api/upload"]["post"]["responses"]["413"]["description"],
                         "Upload exceeds 1 MB")

    def test_swagger_docs_route(self):
        response = self.client.get("/api/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"swagger-ui", response.data)
        self.assertIn(b"/static/swagger-init.js", response.data)
        initializer = self.client.get("/static/swagger-init.js")
        self.assertEqual(initializer.status_code, 200)
        self.assertIn(b"/api/openapi.json", initializer.data)

    def test_upload_database_failure_returns_json_error(self):
        self.app.config["DATABASE"] = self.temp_dir.name
        response = self.upload()
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())

    def test_existing_dashboard_and_form_routes_remain_available(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.post(
            "/upload",
            data={"file": (io.BytesIO(VALID_CSV), "dashboard.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post("/screen").status_code, 302)
        self.assertEqual(self.client.post("/audit/verify").status_code, 302)


if __name__ == "__main__":
    unittest.main()
