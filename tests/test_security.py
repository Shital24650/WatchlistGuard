"""Authentication, authorization, CSRF, session, and security-event coverage."""
import os
import io
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

from app import create_app, _login_attempts, _login_attempts_lock
from tests.security_client import AuthenticatedTestClient
from watchlistguard.auth import create_user
from watchlistguard.db import close, connect, initialize


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "security.sqlite3")
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "test-security-key",
                               "SESSION_COOKIE_SECURE": False})
        self.app.test_client_class = AuthenticatedTestClient
        self.client = self.app.test_client()
        with _login_attempts_lock:
            _login_attempts.clear()
        conn = connect(self.db_path)
        try:
            initialize(conn)
            for username, role in (("admin-user", "ADMINISTRATOR"), ("analyst-user", "ANALYST"), ("auditor-user", "AUDITOR")):
                create_user(conn, username, "Synthetic-password-for-tests-2026", role)
            conn.commit()
        finally:
            close(conn)

    def tearDown(self):
        self.temp.cleanup()

    def sign_in(self, username, client=None):
        client = client or self.client
        token = client.get("/api/auth/csrf").get_json()["csrf_token"]
        return client.post("/api/auth/login", json={"username": username,
            "password": "Synthetic-password-for-tests-2026"}, headers={"X-CSRF-Token": token})

    def _create_user(self, username, role):
        conn = connect(self.db_path)
        try:
            user = create_user(conn, username, "Synthetic-password-for-tests-2026", role)
            conn.commit()
            return user["id"]
        finally:
            close(conn)

    def _user_id(self, username):
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT id FROM app_users WHERE username=?", (username,)).fetchone()[0]
        finally:
            close(conn)

    def _active_admin_count(self):
        conn = connect(self.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM app_users WHERE role='ADMINISTRATOR' AND active=1").fetchone()[0]
        finally:
            close(conn)

    def test_unauthenticated_access_is_denied(self):
        self.assertEqual(self.client.get("/api/report").status_code, 401)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_administrator_can_manage_users(self):
        self.assertEqual(self.sign_in("admin-user").status_code, 200)
        created = self.client.post("/api/admin/users", json={"username": "new-analyst",
            "password": "another-synthetic-password", "role": "ANALYST"})
        self.assertEqual(created.status_code, 201)
        self.assertNotIn(b"password", created.data.lower())
        self.assertEqual(self.client.get("/api/admin/users").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/settings").status_code, 200)
        updated = self.client.put("/api/admin/settings", json={"upload_max_bytes": 900000,
                                                                "session_timeout_minutes": 20})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["upload_max_bytes"], 900000)
        self.assertEqual(self.client.put("/api/admin/settings", json={"session_timeout_minutes": 3.5}).status_code, 400)
        self.assertEqual(self.client.post("/api/admin/users", json=[]).status_code, 400)
        self.assertEqual(self.client.put(f"/api/admin/users/{created.get_json()['id']}/role",
            json={"role": "AUDITOR"}).status_code, 200)

    def test_only_active_administrator_cannot_be_demoted(self):
        self.sign_in("admin-user")
        response = self.client.put(f"/api/admin/users/{self._user_id('admin-user')}/role",
                                   json={"role": "ANALYST"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "At least one active administrator must remain."})
        self.assertEqual(self._active_admin_count(), 1)

    def test_one_of_multiple_administrators_can_be_demoted(self):
        self._create_user("second-admin", "ADMINISTRATOR")
        self.sign_in("admin-user")
        response = self.client.put(f"/api/admin/users/{self._user_id('admin-user')}/role",
                                   json={"role": "AUDITOR"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_admin_count(), 1)

    def test_promote_replacement_before_demoting_original(self):
        analyst_id = self._user_id("analyst-user")
        self.sign_in("admin-user")
        promoted = self.client.put(f"/api/admin/users/{analyst_id}/role", json={"role": "ADMINISTRATOR"})
        self.assertEqual(promoted.status_code, 200)
        demoted = self.client.put(f"/api/admin/users/{self._user_id('admin-user')}/role",
                                  json={"role": "ANALYST"})
        self.assertEqual(demoted.status_code, 200)
        self.assertEqual(self._active_admin_count(), 1)

    def test_concurrent_self_demotion_keeps_an_active_administrator(self):
        self._create_user("second-admin", "ADMINISTRATOR")
        other_client = self.app.test_client()
        self.assertEqual(self.sign_in("admin-user").status_code, 200)
        self.assertEqual(self.sign_in("second-admin", other_client).status_code, 200)
        user_ids = {"admin-user": self._user_id("admin-user"),
                    "second-admin": self._user_id("second-admin")}
        barrier = threading.Barrier(2)
        responses, failures = [], []

        def demote_self(username, client):
            try:
                barrier.wait(timeout=5)
                responses.append(client.put(f"/api/admin/users/{user_ids[username]}/role",
                                            json={"role": "ANALYST"}).status_code)
            except Exception as exc:  # surface thread failures in the assertion below
                failures.append(exc)

        threads = [threading.Thread(target=demote_self, args=("admin-user", self.client)),
                   threading.Thread(target=demote_self, args=("second-admin", other_client))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads), "concurrent role change hung")
        self.assertFalse(failures, failures)
        self.assertCountEqual(responses, [200, 400])
        self.assertEqual(self._active_admin_count(), 1)

    def test_create_admin_cli_recovers_when_users_exist_without_active_admin(self):
        recovery_db = os.path.join(self.temp.name, "recovery.sqlite3")
        conn = connect(recovery_db)
        try:
            initialize(conn)
            create_user(conn, "recovery-analyst", "Synthetic-password-for-tests-2026", "ANALYST")
            conn.commit()
        finally:
            close(conn)
        import main as cli
        with patch("sys.argv", ["main.py", "--db", recovery_db, "create-admin"]), \
             patch.object(cli, "getpass", side_effect=["Synthetic-recovery-password-2026", "Synthetic-recovery-password-2026"]), \
             patch("builtins.input", return_value="recovery-admin"):
            self.assertEqual(cli.main(), 0)
        conn = connect(recovery_db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM app_users WHERE role='ADMINISTRATOR' AND active=1").fetchone()[0], 1)
        finally:
            close(conn)

    def test_analyst_can_screen_and_read_but_cannot_administer_or_upload(self):
        self.sign_in("analyst-user")
        self.assertEqual(self.client.get("/api/report").status_code, 200)
        self.assertEqual(self.client.post("/api/screen").status_code, 200)
        self.assertEqual(self.client.post("/api/admin/users", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/settings").status_code, 403)
        self.assertEqual(self.client.get("/api/audit").status_code, 403)
        self.assertEqual(self.client.post("/api/audit/verify").status_code, 403)
        self.assertEqual(self.client.post("/api/upload").status_code, 403)

    def test_auditor_is_read_only(self):
        self.sign_in("auditor-user")
        self.assertEqual(self.client.get("/api/report").status_code, 200)
        self.assertEqual(self.client.get("/api/audit").status_code, 200)
        self.assertEqual(self.client.post("/api/screen").status_code, 403)
        self.assertEqual(self.client.post("/api/audit/verify").status_code, 403)
        self.assertEqual(self.client.post("/api/upload").status_code, 403)

    def test_csrf_rejects_missing_and_invalid_tokens(self):
        self.sign_in("admin-user")
        self.assertEqual(self.client.post("/api/screen", headers={"X-CSRF-Token": "wrong"}).status_code, 400)
        self.assertEqual(self.client.post("/api/screen", headers={"X-CSRF-Token": ""}).status_code, 400)

    def test_login_rejects_invalid_credentials_and_audits_failure(self):
        token = self.client.get("/api/auth/csrf").get_json()["csrf_token"]
        response = self.client.post("/api/auth/login", json={"username": "admin-user", "password": "wrong"},
                                    headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 401)
        conn = connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event_type='LOGIN_FAILURE'").fetchone()[0], 1)
            self.assertNotIn("wrong", conn.execute("SELECT details FROM audit_logs WHERE event_type='LOGIN_FAILURE'").fetchone()[0])
        finally:
            close(conn)

    def test_login_sql_injection_attempt_does_not_authenticate(self):
        token = self.client.get("/api/auth/csrf").get_json()["csrf_token"]
        response = self.client.post("/api/auth/login", json={"username": "' OR '1'='1", "password": "anything"},
                                    headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 401)

    def test_successful_login_is_audited_without_credentials(self):
        response = self.sign_in("admin-user")
        self.assertEqual(response.status_code, 200)
        conn = connect(self.db_path)
        try:
            details = conn.execute("SELECT details FROM audit_logs WHERE event_type='LOGIN_SUCCESS'").fetchone()[0]
            self.assertIn("user_id=", details)
            self.assertNotIn("Synthetic-password-for-tests-2026", details)
        finally:
            close(conn)

    def test_openapi_documents_session_and_csrf(self):
        spec = self.client.get("/api/openapi.json").get_json()
        self.assertIn("sessionCookie", spec["components"]["securitySchemes"])
        self.assertIn("X-CSRF-Token", str(spec["paths"]["/api/auth/login"]))
        self.assertEqual(spec["paths"]["/api/report"]["get"]["security"], [{"sessionCookie": []}])

    def test_login_rate_limit(self):
        token = self.client.get("/api/auth/csrf").get_json()["csrf_token"]
        statuses = [self.client.post("/api/auth/login", json={"username": "bad", "password": "bad"},
                     headers={"X-CSRF-Token": token}).status_code for _ in range(11)]
        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10], 429)

    def test_session_is_rotated_at_login_and_logout(self):
        self.client.get("/api/auth/csrf")
        before = self.client.get_cookie("session").value
        response = self.sign_in("admin-user")
        self.assertEqual(response.status_code, 200)
        after = self.client.get_cookie("session").value
        self.assertNotEqual(before, after)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/report").status_code, 401)

    def test_session_expiration(self):
        self.app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=1)
        self.sign_in("admin-user")
        time.sleep(2.1)
        self.assertEqual(self.client.get("/api/report").status_code, 401)

    def test_password_is_hashed_and_not_returned(self):
        conn = connect(self.db_path)
        try:
            row = conn.execute("SELECT password_hash FROM app_users WHERE username='admin-user'").fetchone()
            self.assertNotIn("Synthetic-password-for-tests-2026", row["password_hash"])
            self.assertTrue(row["password_hash"].startswith("scrypt:"))
        finally:
            close(conn)

    def test_secure_response_headers_and_existing_csp(self):
        response = self.sign_in("admin-user")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_production_requires_secret_and_marks_session_cookie_secure(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY is required"):
                create_app()
        app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "test",
                          "SESSION_COOKIE_SECURE": True})
        app.test_client_class = AuthenticatedTestClient
        client = app.test_client()
        csrf = client.get("/api/auth/csrf", base_url="https://localhost").get_json()["csrf_token"]
        client.post("/api/auth/login", json={"username": "admin-user", "password": "Synthetic-password-for-tests-2026"},
                    headers={"X-CSRF-Token": csrf}, base_url="https://localhost")
        self.assertTrue(client.get_cookie("session").secure)
        with patch.dict(os.environ, {"WATCHLISTGUARD_COOKIE_SECURE": "true"}, clear=True):
            configured = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "test"})
        self.assertTrue(configured.config["SESSION_COOKIE_SECURE"])

    def test_malicious_upload_name_is_sanitized(self):
        self.sign_in("admin-user")
        payload = b"transaction_ref,customer_name,amount,currency\nSYN-UPLOAD,Test User,1,USD\n"
        response = self.client.post("/api/upload", data={"file": (io.BytesIO(payload), "../../evil.csv")},
                                    content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        conn = connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT source_file FROM transactions WHERE transaction_ref='SYN-UPLOAD'").fetchone()[0], "evil.csv")
        finally:
            close(conn)


if __name__ == "__main__":
    unittest.main()
