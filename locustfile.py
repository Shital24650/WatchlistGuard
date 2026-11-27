"""Reproducible synthetic API workload; credentials are supplied via env vars."""
import os
from itertools import count

from locust import HttpUser, between, task

_sequence = count()


class AuthenticatedApiUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        username = os.environ.get("LOADTEST_USERNAME")
        password = os.environ.get("LOADTEST_PASSWORD")
        if not username or not password:
            raise RuntimeError("Set LOADTEST_USERNAME and LOADTEST_PASSWORD for the disposable test environment")
        csrf = self.client.get("/api/auth/csrf", name="auth/csrf").json()["csrf_token"]
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
            name="auth/login",
        )
        if response.status_code != 200:
            raise RuntimeError("Load-test authentication failed; verify the disposable test user")
        self.csrf = self.client.get("/api/auth/csrf", name="auth/csrf/refresh").json()["csrf_token"]

    @task(6)
    def report_page(self):
        self.client.get("/api/report?page=1&page_size=50", name="report/page")

    @task(3)
    def filtered_report(self):
        self.client.get("/api/report?page=1&page_size=25&risk_level=HIGH", name="report/high-page")

    @task(4)
    def keyset_report(self):
        self.client.get("/api/report/cursor?after_id=0&page_size=50", name="report/cursor")

    @task(2)
    def batch_ingestion(self):
        batch_id = next(_sequence)
        rows = ["transaction_ref,customer_name,amount,currency"]
        rows.extend(
            f"LOAD-{batch_id}-{index},Synthetic Customer {index},12.50,USD"
            for index in range(50)
        )
        payload = ("\n".join(rows) + "\n").encode("utf-8")
        self.client.post(
            "/api/upload",
            files={"file": (f"load-{batch_id}.csv", payload, "text/csv")},
            headers={"X-CSRF-Token": self.csrf},
            name="ingestion/batch-50",
        )

    @task(1)
    def screening(self):
        self.client.post("/api/screen", headers={"X-CSRF-Token": self.csrf}, name="screening/run")

    @task(1)
    def audit_read(self):
        self.client.get("/api/audit", name="audit/recent")


class AuthenticationUser(HttpUser):
    """Measure repeated authentication separately from the mixed API profile."""
    weight = 1
    wait_time = between(1.0, 2.0)

    @task
    def authenticate(self):
        username = os.environ.get("LOADTEST_USERNAME")
        password = os.environ.get("LOADTEST_PASSWORD")
        if not username or not password:
            raise RuntimeError("Set LOADTEST_USERNAME and LOADTEST_PASSWORD for the disposable test environment")
        csrf = self.client.get("/api/auth/csrf", name="auth/csrf").json()["csrf_token"]
        self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
            name="auth/login/repeated",
        )
