# V3 database engineering report

## Architecture and implementation

- `watchlistguard/db.py` provides dialect detection, SQLite compatibility, a psycopg 3 connection pool, a qmark SQL adapter, and pooled connection lifecycle handling. SQLite connections remain ordinary `sqlite3.Connection` objects.
- Alembic migration `0001_initial` models the existing transaction, watchlist, screening, audit, and processed-file schema. PostgreSQL initialization requires the operator to run migrations explicitly.
- PostgreSQL write transactions use advisory transaction locks for ingestion idempotency and audit-chain append serialization. Transaction references and processed-file digests retain unique constraints.
- PostgreSQL indexes cover normalized customer lookup, created timestamps, risk classification, and audit hash lookup. Transaction references are indexed by their unique constraint.
- CI provisions PostgreSQL 16, applies migrations, compiles the Python sources, and runs the opt-in integration suite. SQLite remains in a separate full unit test job.

## Verification performed

- Baseline before implementation: `python -m unittest discover -v` — **57 passed, 0 failed, 0 skipped**.
- Review-fix local suite — **67 tests: 60 passed, 0 failed, 7 skipped**. Skips were the PostgreSQL integration tests because no local PostgreSQL service was available.
- `tests/test_db_pool.py` verifies two PostgreSQL URLs get distinct pools, identical URLs reuse a pool, and shutdown cleanup closes and forgets pools.
- PostgreSQL integration regression cases now verify screening writes and its audit record after prior reads, return of the lease, and verification from a separate connection; a synthetic audit failure verifies screening rollback.
- A pooled-lease regression starts an explicit transaction, writes, returns the lease, then verifies through a separate lease that cleanup rolled the write back.
- The application health path test simulates migration validation failure and confirms rollback and lease release. `app.database()` now releases a lease if initialization or seeding raises.
- Top-level PostgreSQL connection contexts use `autocommit=True`, so reads before `with conn` cannot turn the intended transaction into a nested savepoint. Each lease carries its originating URL-keyed pool; cleanup rolls back non-idle leases before returning them.
- GitHub Actions run `45972308470` passed the earlier review-fix commit with all **6 then-current PostgreSQL integration tests**. The final branch commit adds one more lease cleanup test; its CI run is pending.
- Python compilation, Alembic history, offline `alembic upgrade head --sql`, and `git diff --check` passed.
- Bandit passed after replacing report filter SQL assembly with fixed SQL and bound filter parameters; report pagination/filter tests passed.
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
