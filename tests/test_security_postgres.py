"""PostgreSQL regression for atomic last-administrator protection."""
import os
import threading
import unittest

from app import create_app
from watchlistguard.auth import create_user
from watchlistguard.db import close, close_pools, connect, initialize

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")


@unittest.skipUnless(POSTGRES_URL, "NOT RUN: TEST_POSTGRES_URL disposable PostgreSQL unavailable")
class PostgreSQLAdministratorInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["WATCHLISTGUARD_DATABASE_URL"] = POSTGRES_URL
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")

    def setUp(self):
        conn = connect(POSTGRES_URL)
        try:
            conn.execute("TRUNCATE app_users,audit_logs RESTART IDENTITY CASCADE")
            conn.commit()
            initialize(conn)
            create_user(conn, "pg-admin-a", "Synthetic-password-for-tests-2026", "ADMINISTRATOR")
            create_user(conn, "pg-admin-b", "Synthetic-password-for-tests-2026", "ADMINISTRATOR")
            conn.commit()
        finally:
            close(conn)
        self.app = create_app({"TESTING": True, "DATABASE": POSTGRES_URL,
                               "SECRET_KEY": "synthetic-pg-test-secret"})

    def _signed_in_client(self, username):
        client = self.app.test_client()
        token = client.get("/api/auth/csrf").get_json()["csrf_token"]
        response = client.post("/api/auth/login", json={
            "username": username, "password": "Synthetic-password-for-tests-2026",
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 200)
        return client

    def _id(self, username):
        conn = connect(POSTGRES_URL)
        try:
            return conn.execute("SELECT id FROM app_users WHERE username=?", (username,)).fetchone()[0]
        finally:
            close(conn)

    def test_concurrent_postgres_self_demotion_keeps_one_active_administrator(self):
        clients = {"pg-admin-a": self._signed_in_client("pg-admin-a"),
                   "pg-admin-b": self._signed_in_client("pg-admin-b")}
        ids = {name: self._id(name) for name in clients}
        barrier = threading.Barrier(2)
        statuses, failures = [], []

        def demote(username):
            try:
                barrier.wait(timeout=5)
                response = clients[username].put(
                    f"/api/admin/users/{ids[username]}/role", json={"role": "ANALYST"}
                )
                statuses.append(response.status_code)
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=demote, args=(name,)) for name in clients]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertFalse(any(thread.is_alive() for thread in threads), "concurrent PostgreSQL updates hung")
        self.assertFalse(failures, failures)
        self.assertCountEqual(statuses, [200, 400])
        conn = connect(POSTGRES_URL)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM app_users WHERE role='ADMINISTRATOR' AND active=TRUE"
            ).fetchone()[0], 1)
        finally:
            close(conn)

    def tearDown(self):
        close_pools()


if __name__ == "__main__":
    unittest.main()
