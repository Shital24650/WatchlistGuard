# WatchlistGuard

WatchlistGuard is a lightweight transaction-screening portfolio project demonstrating Python, CSV validation, SQLite, Bash, transparent synthetic name matching, risk classification, Flask web development, and SHA-256 hash-chained audit events.

> **DEMO ONLY — SYNTHETIC DATA.** Never upload real customer, personal, payment, or banking information. This educational prototype is not a production AML or sanctions-screening system, does not make real financial decisions, and is not a claim of regulatory compliance or production-grade banking security.

## Features

- Existing CLI retained in main.py.
- Flask dashboard: summary, CSV upload, screening action, results, risk scores/classifications, audit verification, recent activity.
- /health endpoint for hosting health checks.
- SQLite path configurable through WATCHLISTGUARD_DB (or CLI --db).
- CSV upload restricted to .csv, sanitized filenames, 1 MB limit, and generic user-facing errors.
- Parameterized SQL and Jinja autoescaping.
- Gunicorn production WSGI server and Render Blueprint configuration.

## Install and run locally

Requires Python 3.9+, Flask and Gunicorn.

\`\`\`bash
python -m pip install -r requirements.txt
export WATCHLISTGUARD_DB=data/watchlistguard-web.db
export FLASK_SECRET_KEY="replace-with-a-long-random-secret"
flask --app app run --host 127.0.0.1 --port 5000
\`\`\`

Open http://127.0.0.1:5000. The database is initialized automatically. The included data/transactions.csv contains fictional sample records.

For a production-style local run:

\`\`\`bash
gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:\${PORT:-5000} app:app
\`\`\`

Set FLASK_SECRET_KEY to a strong private random value in the hosting environment. Never commit secrets. The application has a random per-process fallback for local demonstration; configure the environment variable for stable sessions across restarts.

## Deploy to Render

render.yaml defines the web service, dependency build command, Gunicorn start command, and /health check.

1. Push the branch to GitHub.
2. In Render, create a new Blueprint instance and select this repository and branch.
3. Confirm the settings from render.yaml and deploy.
4. Add FLASK_SECRET_KEY in the Render environment settings.
5. Confirm the deployed service URL and its /health endpoint return {"status":"ok"}.

**SQLite persistence on free hosting:** Render free web services have an ephemeral filesystem. A SQLite database in the project directory can be reset when the service restarts, redeploys, or sleeps. The included free-tier configuration is suitable for a disposable portfolio demo, not durable storage. For persistent SQLite on Render, attach a persistent disk (where available on a paid service) and set WATCHLISTGUARD_DB to a path on that disk, such as /var/data/watchlistguard.db. SQLite is a single-file database and is not suitable for horizontally scaled multi-instance services. A real multi-user production system needs a managed database and a much broader security architecture.

## Existing CLI

The web app imports existing project modules; it does not replace the CLI.

\`\`\`bash
python main.py --db /tmp/watchlistguard-demo.db ingest data/transactions.csv
python main.py --db /tmp/watchlistguard-demo.db screen
python main.py --db /tmp/watchlistguard-demo.db report
python main.py --db /tmp/watchlistguard-demo.db audit-verify
\`\`\`

Optional Bash scripts: chmod +x scripts/*.sh, then run scripts/ingest.sh data/transactions.csv and scripts/run_screening.sh.

## CSV format

Required headers: transaction_ref, customer_name, amount, currency. Use fictional records only. The web upload limit is 1 MB. The ingestion module validates rows, rejects invalid values, and detects duplicate transactions and repeated files.

## Architecture

\`\`\`text
Browser → Flask routes (app.py)
             ├── CSV upload → ingestion.py → SQLite
             ├── Run screening → service.py → screening.py → SQLite
             ├── Results → service.report_rows() → dashboard template
             ├── Audit check → audit.py → audit_logs
             └── /health → SQLite connectivity check

CLI (main.py) → same underlying project modules
\`\`\`

## Tests and CI

\`\`\`bash
python -m unittest discover -v
\`\`\`

The suite includes existing CLI/module tests and Flask endpoint tests for health, dashboard summary, upload, screening, report display, audit verification, invalid extensions, malformed/missing CSV columns, empty files, upload size limits, and HTML escaping. GitHub Actions installs requirements.txt and runs the complete suite on pushes and pull requests.

## Screening model and limitations

Names are normalized and compared using exact matching or difflib.SequenceMatcher with a threshold of 0.82. Synthetic watchlist weights produce LOW (0–34), MEDIUM (35–74), or HIGH (75–100) scores. The simplified model does not implement aliases, transliteration, date-of-birth/address matching, external list updates, PEP/adverse-media screening, case management, or human review.

The audit log is a SHA-256 hash chain. It is tamper-evident, not tamper-proof; an actor able to rewrite the database and recompute the chain can defeat it. This is a learning/portfolio demonstration only, not a production AML, sanctions, or banking compliance solution.
