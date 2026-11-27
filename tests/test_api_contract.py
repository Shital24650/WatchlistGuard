"""Backward-compatible API response and input contract tests."""
import os
import tempfile
import unittest

from app import create_app
from tests.security_client import sign_in_admin
from watchlistguard.auth import create_user
from watchlistguard.db import close, connect


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp.name, "contract.sqlite3")
        self.app = create_app({
            "TESTING": True,
            "DATABASE": self.database,
            "SECRET_KEY": "api-contract-test-key",
        })
        self.client = sign_in_admin(self.app, self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_report_response_contract_and_empty_page(self):
        response = self.client.get("/api/report?page=1&page_size=20")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(set(body), {"count", "results", "pagination"})
        self.assertEqual(set(body["pagination"]), {"page", "page_size", "total", "total_pages"})
        self.assertEqual(body["results"], [])

    def test_report_contract_retains_pending_and_screened_filters(self):
        response = self.client.get("/api/report?risk_level=pending&screening_status=pending")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 0)
        self.assertEqual(self.client.get("/api/report?risk_level=unknown").status_code, 400)
        self.assertEqual(self.client.get("/api/report?page_size=101").status_code, 400)

    def test_cursor_report_returns_bounded_continuation_without_changing_offset_contract(self):
        conn = connect(self.database)
        try:
            with conn:
                for index in range(3):
                    conn.execute(
                        "INSERT INTO transactions(transaction_ref,customer_name,normalized_name,amount,currency,source_file) "
                        "VALUES(?,?,?,?,?,?)",
                        (f"CURSOR-{index}", f"Synthetic Customer {index}", f"synthetic customer {index}", 4, "USD", "contract.csv"),
                    )
        finally:
            close(conn)

        first = self.client.get("/api/report/cursor?page_size=2").get_json()
        self.assertEqual(first["returned"], 2)
        self.assertTrue(first["pagination"]["has_more"])
        self.assertEqual(set(first["results"][0]), {
            "transaction_ref", "customer_name", "amount", "currency",
            "risk_level", "risk_score", "match_type", "explanation",
        })
        cursor = first["pagination"]["next_after_id"]
        second = self.client.get(f"/api/report/cursor?after_id={cursor}&page_size=2").get_json()
        self.assertEqual(second["returned"], 1)
        self.assertFalse(second["pagination"]["has_more"])
        self.assertEqual([r["transaction_ref"] for r in first["results"] + second["results"]],
                         ["CURSOR-0", "CURSOR-1", "CURSOR-2"])
        self.assertEqual(self.client.get("/api/report/cursor?after_id=-1").status_code, 400)

    def test_openapi_advertises_existing_report_parameters(self):
        document = self.client.get("/api/openapi.json").get_json()
        operation = document["paths"]["/api/report"]["get"]
        self.assertEqual(
            {parameter["name"] for parameter in operation["parameters"]},
            {"page", "page_size", "risk_level", "screening_status"},
        )
        cursor_operation = document["paths"]["/api/report/cursor"]["get"]
        self.assertIn("after_id", {parameter["name"] for parameter in cursor_operation["parameters"]})

    def test_authentication_authorization_and_csrf_contracts_remain_enforced(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/api/admin/users").status_code, 401)
        missing_csrf = self.client.post("/api/screen", headers={"X-CSRF-Token": ""})
        self.assertEqual(missing_csrf.status_code, 400)

        conn = connect(self.database)
        try:
            analyst = create_user(conn, "contract-analyst", "synthetic-contract-password-2026", "ANALYST")
            conn.commit()
        finally:
            close(conn)
        client = self.app.test_client()
        csrf = client.get("/api/auth/csrf").get_json()["csrf_token"]
        login = client.post("/api/auth/login", json={
            "username": analyst["username"], "password": "synthetic-contract-password-2026",
        }, headers={"X-CSRF-Token": csrf})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/api/admin/users").status_code, 403)

    def test_database_connection_failure_has_safe_api_error_contract(self):
        from unittest.mock import patch
        self.app.testing = False
        with patch("app.connect", side_effect=RuntimeError("synthetic connection detail")):
            response = self.client.get("/api/report")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Report could not be generated."})


if __name__ == "__main__":
    unittest.main()
