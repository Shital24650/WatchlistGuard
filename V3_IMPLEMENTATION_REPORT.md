# V3 database engineering report

## Architecture and implementation

- `watchlistguard/db.py` provides dialect detection, SQLite compatibility, a psycopg 3 connection pool, a qmark SQL adapter, and pooled connection lifecycle handling. SQLite connections remain ordinary `sqlite3.Connection` objects.
- Alembic migration `0001_initial` models the existing transaction, watchlist, screening, audit, and processed-file schema. PostgreSQL initialization requires the operator to run migrations explicitly.
- PostgreSQL write transactions use advisory transaction locks for ingestion idempotency and audit-chain append serialization. Transaction references and processed-file digests retain unique constraints.
- PostgreSQL indexes cover normalized customer lookup, created timestamps, risk classification, and audit hash lookup. Transaction references are indexed by their unique constraint.
- CI provisions PostgreSQL 16, applies migrations, compiles the Python sources, and runs the opt-in integration suite. SQLite remains in a separate full unit test job.

## Verification performed

- Baseline before implementation: `python -m unittest discover -v` — **57 passed, 0 failed, 0 skipped**.
- V3 local suite — **61 tests: 57 passed, 0 failed, 4 skipped**. Skips were the PostgreSQL integration tests because no local PostgreSQL service was available.
- GitHub Actions run `45969101232` passed both `unittest` and PostgreSQL jobs. The PostgreSQL job applied Alembic migrations and completed the PostgreSQL integration tests against PostgreSQL 16, including uniqueness, ingestion duplicates/idempotency, screening, pagination/filtering, audit verification, rollback, concurrent writes, and broken-lease reconnection.
- Python compilation, Alembic history, offline `alembic upgrade head --sql`, and `git diff --check` passed.
- No local `EXPLAIN` measurements were available, so this report makes no measured performance claim.

## Files and deployment

- Database adapter and application query changes: `watchlistguard/db.py`, `watchlistguard/ingestion.py`, `watchlistguard/audit.py`, and `watchlistguard/service.py`.
- Migration environment and initial migration: `alembic.ini`, `migrations/env.py`, and `migrations/versions/0001_initial.py`.
- Integration tests and CI: `tests/test_postgres_integration.py` and `.github/workflows/tests.yml`.
- Setup, migration, and configuration guidance: `README.md`.
- Render configuration was not changed. No production database was accessed or migrated and no deployment was performed.

## Limitations

- Existing SQLite rows are not converted automatically; data migration is an operator-managed future task.
- PostgreSQL migration remains explicit and has only been exercised against the disposable PostgreSQL 16 CI service.
- No query-plan measurements or benchmark results are claimed.
- This remains an educational transaction-screening demonstration, not production banking or AML software.
