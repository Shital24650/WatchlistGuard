# WatchlistGuard

WatchlistGuard is an educational transaction-screening portfolio project. It demonstrates CSV ingestion and validation, SQLite persistence, transparent synthetic name matching, risk classification, a Flask dashboard and JSON API, and SHA-256 hash-chained audit events.

> **DEMO ONLY — SYNTHETIC DATA.** Never upload real customer, personal, payment, or banking information. This prototype is not a production AML or sanctions-screening system, does not make real financial decisions, and is not a claim of regulatory compliance.

## Features

- CLI workflow retained in `main.py` for ingest, screen, report, and audit verification.
- Flask dashboard with summary, CSV upload, screening action, results, and audit status.
- JSON API documented with OpenAPI 3.0.3 and interactive Swagger UI.
- SQLite path configurable with `WATCHLISTGUARD_DB` (or CLI `--db`).
- Optional PostgreSQL backend using psycopg 3 and a bounded connection pool; SQLite remains the default.
- Alembic versioned PostgreSQL schema with explicit operator-run migrations.
- Password-hashed user authentication, expiring sessions, CSRF validation, and server-side role checks.
- CSV upload restricted to `.csv`, sanitized filenames, and a 1 MB file limit.
- Atomic idempotent ingestion: identical file bytes are skipped by SHA-256; changed files are deduplicated by the globally unique `transaction_ref` database constraint.
- SQL-paginated report API with risk-level and screening-status filters.
- Parameterized SQL, Jinja autoescaping, generic API errors, and security response headers.
- Gunicorn WSGI server and Render Blueprint configuration.

## Architecture

```text
Browser / API client
       |
       v
Flask app.py
  |-- dashboard routes: /, /upload, /screen, /audit/verify
  |-- health route: /health
  |-- JSON API: /api/upload, /api/screen, /api/report, /api/audit/verify
  |-- API docs: /api/openapi.json, /api/docs
       |
       v
watchlistguard/
  |-- ingestion.py  -> CSV validation, deduplication, file fingerprints
  |-- service.py    -> screening orchestration and report rows
  |-- screening.py  -> synthetic name matching and risk bands
  |-- db.py         -> SQLite schema, connections, synthetic watchlist seed
  |-- audit.py      -> SHA-256 audit-chain append and verification
       ^
       |
main.py CLI --------+
       |
       v
SQLite (default) or PostgreSQL (configured URL)
```

## API endpoints

All API responses use JSON except the Swagger UI HTML route. Screening and administrative routes require an authenticated session. Public routes are limited to health, login/CSRF bootstrap, API documentation, and the OpenAPI document.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Check application and database availability |
| GET | `/api/openapi.json` | Retrieve the OpenAPI 3.0.3 document |
| GET | `/api/docs` | Interactive Swagger UI |
| POST | `/api/upload` | Upload a CSV as multipart field `file` |
| POST | `/api/screen` | Screen all pending transactions |
| GET | `/api/report` | Return a paginated, filterable screening report |
| POST | `/api/audit/verify` | Verify the audit chain and record the check |
| GET | `/api/auth/csrf` | Obtain a CSRF token before login |
| POST | `/api/auth/login` | Establish an authenticated session |
| POST | `/api/auth/logout` | End the authenticated session |
| GET | `/api/audit` | Read audit records (administrator or auditor) |
| GET/POST | `/api/admin/users` | List or create users (administrator) |
| PUT | `/api/admin/users/{id}/role` | Change a user's role (administrator) |
| GET/PUT | `/api/admin/settings` | Read or update process-local settings (administrator) |

Upload requires CSV headers `transaction_ref,customer_name,amount,currency`. The schema defines `transactions.transaction_ref` as `UNIQUE`, so that field—not customer name, amount, or file name—is the transaction identity. Byte-identical files are skipped by SHA-256 (`skipped_file=1`). Changed files are checked row-by-row: an existing reference increments `duplicates` and leaves the original row unchanged, while other valid rows in the same file are inserted. Invalid rows increment `rejected`. A SQLite write reservation serializes upload writers and the unique constraint is the final duplicate guard.

Successful upload responses include `inserted`, `rejected`, `duplicates`, and `skipped_file`. Invalid uploads return 400, files above 1 MB return 413, audit-chain tampering returns 409, and unexpected API failures return a generic 500 response.

### Report pagination and filters

`GET /api/report` accepts these optional query parameters:

| Parameter | Default | Allowed values |
|---|---:|---|
| `page` | 1 | Integer ≥ 1 |
| `page_size` | 20 | Integer 1–100 |
| `risk_level` | — | `PENDING`, `LOW`, `MEDIUM`, `HIGH` |
| `screening_status` | — | `PENDING`, `SCREENED` |

Filters can be combined. Invalid values return HTTP 400. Rows are ordered by transaction insertion ID. The SQL query applies `LIMIT` and `OFFSET`; the endpoint does not load the full report into Python memory. The existing `count` field remains the total number of matching rows, and a new `pagination` object describes the requested page.

```bash
curl "http://127.0.0.1:5000/api/report?page=1&page_size=20"
curl "http://127.0.0.1:5000/api/report?risk_level=HIGH&screening_status=SCREENED&page=2&page_size=10"
```

Example response (synthetic):

```json
{
  "count": 3,
  "results": [
    {
      "transaction_ref": "SYN-1001",
      "customer_name": "Amina Rahman",
      "amount": 125.5,
      "currency": "USD",
      "risk_level": "HIGH",
      "risk_score": 90,
      "match_type": "EXACT",
      "explanation": "Synthetic watchlist match"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 1,
    "total": 3,
    "total_pages": 3
  }
}
```


For protected API calls, first obtain a token from `/api/auth/csrf`, log in with `/api/auth/login`, then send the returned session cookie and the current `X-CSRF-Token` on every POST/PUT/PATCH/DELETE request. No example credentials are provided.

Example (after establishing the session):

```bash
curl -b cookies.txt -H "X-CSRF-Token: TOKEN" -F "file=@data/transactions.csv" http://127.0.0.1:5000/api/upload
curl -b cookies.txt -H "X-CSRF-Token: TOKEN" -X POST http://127.0.0.1:5000/api/screen
curl -b cookies.txt http://127.0.0.1:5000/api/report
curl -b cookies.txt -H "X-CSRF-Token: TOKEN" -X POST http://127.0.0.1:5000/api/audit/verify
```

## Local setup

Requires Python 3.9+.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
export WATCHLISTGUARD_DB=data/watchlistguard-local.db
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
flask --app app run --host 127.0.0.1 --port 5000
```

Open `http://127.0.0.1:5000` for the dashboard or `http://127.0.0.1:5000/api/docs` for Swagger UI. The database is initialized automatically. The included `data/transactions.csv` contains fictional sample records.

### Database configuration and migrations

`WATCHLISTGUARD_DB` remains the SQLite file path (default `data/watchlistguard.db`). Set `WATCHLISTGUARD_DATABASE_URL` to select PostgreSQL; accepted URL forms are `postgresql://...` and `postgres://...`. PostgreSQL requires psycopg 3 with its binary and pool extras. `WATCHLISTGUARD_DB_POOL_SIZE` controls the bounded pool (default 5). The CLI `--db` accepts a SQLite path or PostgreSQL URL.

For a fresh PostgreSQL database, create an empty database and explicitly apply:

```bash
export WATCHLISTGUARD_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DB'
alembic upgrade head
```

The application refuses to create or migrate PostgreSQL schemas at request time. SQLite continues to initialize its demo schema automatically. For an existing PostgreSQL installation, take a verified backup, inspect `alembic current` and `alembic history`, then apply reviewed migrations during a maintenance window. The initial migration creates schema only; it does **not** transfer rows from an existing SQLite file. Do not point migration commands at production without an approved backup and change process. No production database was used here.

The PostgreSQL schema uses identity keys, foreign keys, unique constraints, checks, and indexes for normalized-name lookup, creation time, risk level, and the audit hash chain. Unique constraints provide transaction-reference and file-fingerprint idempotency. Transaction-scoped advisory locks serialize file fingerprint checks and audit-chain appends across PostgreSQL workers. SQLite retains `BEGIN IMMEDIATE` for ingestion serialization.

For a production-style local process:

```bash
gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT:-5000} app:app
```

Set `FLASK_SECRET_KEY` to a strong private random value in hosting. Never commit secrets.

### Authentication and roles

Bootstrap an administrator locally with `python main.py create-admin` (or `python main.py --db "$WATCHLISTGUARD_DATABASE_URL" create-admin` for PostgreSQL). The command prompts interactively for a username and password and refuses when an active administrator already exists. It can restore administrator access if there are users but no active administrator; run it only from a trusted host with authorized database access. There are no default credentials or self-registration routes. Administrators create additional users through the administrator-only API. Role changes are serialized in a database transaction and cannot demote the final active administrator. No account-deactivation route is provided.

Passwords are stored with Werkzeug's scrypt password hash. Login clears and rebuilds the signed session; sessions expire after 30 minutes of inactivity. Cookies are HttpOnly and SameSite=Lax; Secure is enabled for Render/production and can be enabled elsewhere with `WATCHLISTGUARD_COOKIE_SECURE=true`. Production startup requires a configured `FLASK_SECRET_KEY`. Unsafe browser and API requests require a session-bound CSRF token, sent as a form field or `X-CSRF-Token` header. Obtain one from `GET /api/auth/csrf` before posting credentials to `/api/auth/login`.

| Role | Permissions |
|---|---|
| Administrator | Manage users and roles; ingest transactions; run screening; read results and audit records; verify the audit chain. |
| Analyst | Run screening and read screening results. Cannot ingest transactions or access administrative and audit-record routes. |
| Auditor | Read screening results and audit records. Cannot modify transactions, screen, or manage settings/users. |

Authorization is checked by server-side decorators on every protected route. Administrators can update the upload size ceiling (up to the fixed 1 MB safety cap) and session timeout (5–120 minutes) through `/api/admin/settings`; these settings apply only to the current process and should be configured consistently across workers. Authentication successes/failures, logout, user creation, role changes, settings changes, screening, ingestion, and audit verification are recorded without credentials. Login throttling allows 10 failed attempts per client IP per 60 seconds and uses a process-local in-memory counter; deployments with more than one worker need a shared rate-limit store for cross-worker enforcement.

## CLI

The Flask app reuses the existing project modules; it does not replace the CLI.

```bash
python main.py --db /tmp/watchlistguard-demo.db ingest data/transactions.csv
python main.py --db /tmp/watchlistguard-demo.db screen
python main.py --db /tmp/watchlistguard-demo.db report
python main.py --db /tmp/watchlistguard-demo.db audit-verify
python main.py --db /tmp/watchlistguard-demo.db create-admin
```

Optional Bash helpers: `scripts/ingest.sh data/transactions.csv` and `scripts/run_screening.sh`. These scripts use the CLI's default database unless the CLI arguments are changed.

## Tests

Run the full suite:

```bash
python -m unittest discover -v
```

The tests cover the existing module/CLI behavior and Flask dashboard/API behavior. API integration tests create a fresh temporary directory and SQLite database per test; they do not use the configured live database or sample JSON/data files. Coverage includes health, valid and invalid uploads, malformed CSV, upload size, screening, reporting, audit success and tampering, authentication, roles, CSRF, sessions, rate limiting, password hashing, security events, OpenAPI JSON, Swagger UI, and existing form routes.

Install `requirements-dev.txt` for CI tools (Bandit and `openapi-spec-validator`). GitHub Actions runs the SQLite/security suites, Bandit, OpenAPI contract validation, Python compilation, Alembic validation, and PostgreSQL integration tests. PostgreSQL integration tests require a **disposable** empty database selected with `TEST_POSTGRES_URL`; without it they are reported as skipped (`NOT RUN`). The PostgreSQL CI job uses a PostgreSQL 16 service container and a dedicated test database. Never set these test variables to a production or Render URL.

## Deployment

The repository includes `render.yaml` for a Gunicorn web service and `/health` health check.

1. Push the desired branch to GitHub.
2. In Render, create a Blueprint instance and select this repository and branch.
3. Review the settings from `render.yaml` and deploy.
4. Configure `FLASK_SECRET_KEY` in the Render environment.
5. Check the deployed `/health` endpoint.

**Storage limitation:** Render free web services have an ephemeral filesystem. A SQLite database in the application directory may be reset after restart, redeploy, or sleep. This configuration is suitable for a disposable portfolio demo, not durable storage. Persistent SQLite requires a persistent disk where supported; a PostgreSQL URL can target an appropriately managed non-production database. This code does not create hosting resources, change Render configuration, migrate production data, or deploy branches. The demo has no external sanctions-list updates, distributed rate-limit backend, or production case-management workflow.

V4 adds an `app_users` table automatically to SQLite databases. PostgreSQL installations require the explicit `alembic upgrade head` migration before using V4; no existing records are copied or changed by a data migration. Render must have `FLASK_SECRET_KEY` configured before the V4 application starts. This repository change does not edit Render service settings or deploy the branch.

## Screening model and limitations

Names are normalized and compared using exact matching or `difflib.SequenceMatcher` with a threshold of 0.82. Synthetic watchlist weights produce LOW (0–34), MEDIUM (35–74), or HIGH (75–100) scores. The simplified model does not implement aliases, transliteration, date-of-birth/address matching, external list updates, PEP/adverse-media screening, case management, or human review.

The audit log is tamper-evident, not tamper-proof: an actor able to rewrite the database and recompute the chain can defeat it. This is a learning/portfolio demonstration only.
