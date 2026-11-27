"""Request telemetry and health checks use safe, stable response contracts."""
import io
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from container_entrypoint import database_url_from_environment


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "DATABASE": os.path.join(self.temp.name, "observability.db"),
            "SECRET_KEY": "test-only-secret",
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_liveness_does_not_require_database(self):
        with patch("app.connect", side_effect=AssertionError("database should not be checked")):
            response = self.client.get("/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_readiness_checks_database_and_keeps_generic_failure_body(self):
        with patch("app.connect", side_effect=RuntimeError("postgres://user:secret@db/password")):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "unavailable"})

    def test_readiness_closes_connection_when_connectivity_query_fails(self):
        connection = unittest.mock.MagicMock()
        connection.execute.side_effect = RuntimeError("database credential detail")
        with patch("app.connect", return_value=connection), \
                patch("app.initialize"), patch("app.seed_watchlist"):
            response = self.client.get("/ready")
        self.assertEqual(response.status_code, 503)
        connection.close.assert_called_once_with()

    def test_server_request_id_is_returned_and_logs_omit_query_and_caller_header(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(self.app.logger.handlers[0].formatter)
        self.app.logger.addHandler(handler)
        try:
            response = self.client.get("/live?token=private", headers={"X-Request-ID": "caller-secret-123"})
        finally:
            self.app.logger.removeHandler(handler)
        self.assertRegex(response.headers["X-Request-ID"], r"^[a-f0-9]{32}$")
        record = json.loads(stream.getvalue())
        self.assertEqual(record["request_id"], response.headers["X-Request-ID"])
        self.assertEqual(record["path"], "/live")
        self.assertIn("duration_ms", record)
        self.assertNotIn("private", stream.getvalue())
        self.assertNotIn("caller-secret-123", stream.getvalue())

    def test_request_id_is_generated_when_client_supplies_one(self):
        response = self.client.get("/live", headers={"X-Request-ID": "client-id"})
        self.assertRegex(response.headers["X-Request-ID"], r"^[a-f0-9]{32}$")
        self.assertNotEqual(response.headers["X-Request-ID"], "client-id")

    def test_unhandled_api_failure_returns_generic_body_and_safe_log(self):
        self.app.testing = False

        def fail_request():
            raise RuntimeError("postgres://user:secret@db/password")

        self.app.add_url_rule("/api/test-failure", view_func=fail_request)
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(self.app.logger.handlers[0].formatter)
        self.app.logger.addHandler(handler)
        try:
            response = self.client.get("/api/test-failure?token=private")
        finally:
            self.app.logger.removeHandler(handler)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "An unexpected server error occurred."})
        self.assertIn('"error_type":"RuntimeError"', stream.getvalue())
        self.assertNotIn("secret@db", stream.getvalue())
        self.assertNotIn("private", stream.getvalue())

    def test_production_requires_secret_and_pool_size_is_bounded(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY is required"):
                create_app()
        with patch.dict(os.environ, {"WATCHLISTGUARD_DB_POOL_SIZE": "0"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WATCHLISTGUARD_DB_POOL_SIZE"):
                create_app()
        with patch.dict(os.environ, {"WATCHLISTGUARD_DB_POOL_TIMEOUT": "31"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "WATCHLISTGUARD_DB_POOL_TIMEOUT"):
                create_app()

    def test_compose_postgres_credentials_are_url_encoded(self):
        url = database_url_from_environment({
            "POSTGRES_USER": "demo/user",
            "POSTGRES_PASSWORD": "p@ss:/word%?#",
            "POSTGRES_DB": "watchlist db",
            "POSTGRES_HOST": "postgres",
            "POSTGRES_PORT": "5432",
        })
        self.assertEqual(
            url,
            "postgresql://demo%2Fuser:p%40ss%3A%2Fword%25%3F%23@postgres:5432/watchlist%20db",
        )

    def test_compose_postgres_credentials_have_no_password_fallback(self):
        self.assertIsNone(database_url_from_environment({}))
        with self.assertRaisesRegex(RuntimeError, "POSTGRES_PASSWORD"):
            database_url_from_environment({"POSTGRES_USER": "demo", "POSTGRES_DB": "watchlistguard"})


if __name__ == "__main__":
    unittest.main()
