# V4 security engineering report

## Architecture and controls

- Passwords use Werkzeug scrypt hashes. No default users or credentials are created; `python main.py create-admin` interactively bootstraps an administrator only when none is active, including recovery when other non-admin users exist.
- Flask signed sessions rotate on successful login, expire after 30 minutes by default, and use HttpOnly, SameSite=Lax, and production Secure cookies. Production/Render startup fails when `FLASK_SECRET_KEY` is missing.
- Server-side route decorators enforce Administrator, Analyst, and Auditor permissions. Admins manage users/roles and process-local upload/session settings; analysts screen and read results; auditors read results and audit records. Role changes serialize under a PostgreSQL transaction advisory lock or SQLite `BEGIN IMMEDIATE`; demoting the final active administrator is rejected. There is no account-deactivation route.
- All unsafe browser/API requests require a session-bound CSRF token. The existing CSP is retained. Response headers include no-sniff, frame denial, referrer policy, no-store, permissions policy, and HSTS for secure/production requests.
- Login is throttled at 10 failed attempts per client IP per 60 seconds. This is process-local; multi-worker deployments need a shared limiter.
- User creation, role changes, settings changes, login success/failure, logout, ingestion, screening, and audit verification are logged without password/session/token values.
- Upload checks retain extension, filename, file size, and CSV validation. PostgreSQL user creation is an explicit Alembic migration (`0002_app_users`); no production schema changes run at startup.

## Verification performed

- `python -m unittest discover -v`: **90 tests: 81 passed, 0 failed, 9 skipped**. All nine skipped tests require `TEST_POSTGRES_URL`; no local PostgreSQL service is available.
- The suite includes the original CLI, dashboard, ingestion, pagination, and audit tests, plus role permissions, last-active-administrator protection, concurrent role changes, CLI recovery bootstrap, unauthenticated access, CSRF, password hashing/storage, login failures/throttling, session rotation/expiry, security events, and upload filename validation.
- `python -m unittest tests.test_security -v`: **21 passed, 0 failed, 0 skipped**.
- `bandit -q -r app.py main.py watchlistguard`: passed with no findings after replacing dynamic report SQL composition with a fixed parameterized query.
- `openapi-spec-validator` validated the served OpenAPI document successfully.
- Python compilation, `git diff --check`, Alembic history, and offline SQL generation for `alembic upgrade head` passed.
- The V3 PostgreSQL 16 review-fix job passed on run `45974533448`; V4 hosted CI including the PostgreSQL administrator concurrency test is pending.
- No local query plan/EXPLAIN measurements are recorded; no performance improvement is claimed.
- `render.yaml` and production database/environment settings were not changed; no deployment or production database was accessed.

## Limitations and deployment notes

- `FLASK_SECRET_KEY` must be configured in Render before V4 starts. Render service configuration was intentionally left untouched.
- PostgreSQL deployments must explicitly run `alembic upgrade head` before V4 use. The migration adds users only; it does not move SQLite rows.
- Rate limits and administrator-adjustable settings are process-local and are not shared between workers or persisted. Keep the app at one worker or add shared storage before scaling.
- This educational demonstration is not production banking, AML, or sanctions software.
