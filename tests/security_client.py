"""Test helper authenticates legacy route regression cases with synthetic users."""
from flask.testing import FlaskClient


class AuthenticatedTestClient(FlaskClient):
    def _add_csrf(self, kwargs):
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        with self.session_transaction() as session:
            token = session.get("csrf_token")
        if token:
            kwargs["headers"].setdefault("X-CSRF-Token", token)

    def post(self, *args, **kwargs):
        self._add_csrf(kwargs)
        return super().post(*args, **kwargs)

    def put(self, *args, **kwargs):
        self._add_csrf(kwargs)
        return super().put(*args, **kwargs)


def sign_in_admin(app, database_path):
    from watchlistguard.auth import create_user
    from watchlistguard.db import close, connect, initialize, seed_watchlist
    conn = connect(database_path)
    try:
        initialize(conn)
        seed_watchlist(conn)
        try:
            create_user(conn, "test-admin", "synthetic-test-password-2026", "ADMINISTRATOR")
            conn.commit()
        except Exception:
            conn.rollback()
    finally:
        close(conn)
    app.test_client_class = AuthenticatedTestClient
    client = app.test_client()
    csrf = client.get("/api/auth/csrf").get_json()["csrf_token"]
    client.post("/api/auth/login", json={"username": "test-admin", "password": "synthetic-test-password-2026"},
                headers={"X-CSRF-Token": csrf})
    return client
