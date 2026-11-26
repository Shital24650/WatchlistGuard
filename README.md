# WatchlistGuard

WatchlistGuard is an educational transaction-screening portfolio project. It demonstrates CSV ingestion and validation, SQLite persistence, transparent synthetic name matching, risk classification, a Flask dashboard and JSON API, and SHA-256 hash-chained audit events.

> **DEMO ONLY — SYNTHETIC DATA.** Never upload real customer, personal, payment, or banking information. This prototype is not a production AML or sanctions-screening system, does not make real financial decisions, and is not a claim of regulatory compliance.

## Features

- CLI workflow retained in `main.py` for ingest, screen, report, and audit verification.
- Flask dashboard with summary, CSV upload, screening action, results, and audit status.
- JSON API documented with OpenAPI 3.0.3 and interactive Swagger UI.
- SQLite path configurable with `WATCHLISTGUARD_DB` (or CLI `--db`).
- CSV upload restricted to `.csv`, sanitized filenames, and a 1 MB file limit.
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
SQLite database (configured path)
```

## API endpoints

All API responses use JSON except the Swagger UI HTML route. The API is local/demo-oriented and currently has no authentication or authorization.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Check application and SQLite availability |
| GET | `/api/openapi.json` | Retrieve the OpenAPI 3.0.3 document |
| GET | `/api/docs` | Interactive Swagger UI |
| POST | `/api/upload` | Upload a CSV as multipart field `file` |
| POST | `/api/screen` | Screen all pending transactions |
| GET | `/api/report` | Return screening report rows |
| POST | `/api/audit/verify` | Verify the audit chain and record the check |

Upload requires CSV headers `transaction_ref,customer_name,amount,currency`. A successful response includes `inserted`, `rejected`, `duplicates`, and `skipped_file` counts. Invalid uploads return 400, files above 1 MB return 413, audit-chain tampering returns 409, and unexpected API failures return a generic 500 response.

Example:

```bash
curl -F "file=@data/transactions.csv" http://127.0.0.1:5000/api/upload
curl -X POST http://127.0.0.1:5000/api/screen
curl http://127.0.0.1:5000/api/report
curl -X POST http://127.0.0.1:5000/api/audit/verify
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

For a production-style local process:

```bash
gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:${PORT:-5000} app:app
```

Set `FLASK_SECRET_KEY` to a strong private random value in hosting. Never commit secrets.

## CLI

The Flask app reuses the existing project modules; it does not replace the CLI.

```bash
python main.py --db /tmp/watchlistguard-demo.db ingest data/transactions.csv
python main.py --db /tmp/watchlistguard-demo.db screen
python main.py --db /tmp/watchlistguard-demo.db report
python main.py --db /tmp/watchlistguard-demo.db audit-verify
```

Optional Bash helpers: `scripts/ingest.sh data/transactions.csv` and `scripts/run_screening.sh`. These scripts use the CLI's default database unless the CLI arguments are changed.

## Tests

Run the full suite:

```bash
python -m unittest discover -v
```

The tests cover the existing module/CLI behavior and Flask dashboard/API behavior. API integration tests create a fresh temporary directory and SQLite database per test; they do not use the configured live database or sample JSON/data files. Coverage includes health, valid and invalid uploads, malformed CSV, upload size, screening, reporting, audit success and tampering, OpenAPI JSON, Swagger UI, and existing form routes.

## Deployment

The repository includes `render.yaml` for a Gunicorn web service and `/health` health check.

1. Push the desired branch to GitHub.
2. In Render, create a Blueprint instance and select this repository and branch.
3. Review the settings from `render.yaml` and deploy.
4. Configure `FLASK_SECRET_KEY` in the Render environment.
5. Check the deployed `/health` endpoint.

**Storage limitation:** Render free web services have an ephemeral filesystem. A SQLite database in the application directory may be reset after restart, redeploy, or sleep. This configuration is suitable for a disposable portfolio demo, not durable storage. Persistent SQLite requires a persistent disk where supported; horizontally scaled production deployments should use a managed database. The demo API has no authentication, rate limiting, external sanctions-list updates, or production case-management workflow.

## Screening model and limitations

Names are normalized and compared using exact matching or `difflib.SequenceMatcher` with a threshold of 0.82. Synthetic watchlist weights produce LOW (0–34), MEDIUM (35–74), or HIGH (75–100) scores. The simplified model does not implement aliases, transliteration, date-of-birth/address matching, external list updates, PEP/adverse-media screening, case management, or human review.

The audit log is tamper-evident, not tamper-proof: an actor able to rewrite the database and recompute the chain can defeat it. This is a learning/portfolio demonstration only.
