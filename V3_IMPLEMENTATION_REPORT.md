# V3 database engineering report

## Scope and decisions

- Retained SQLite as the default and left its schema initialization, `BEGIN IMMEDIATE`, row format, CLI, and existing SQL behavior intact.
- Added `WATCHLISTGUARD_DATABASE_URL` / PostgreSQL URL selection, a small qmark-to-psycopg adapter, integer-and-name-compatible mapping rows, and a bounded psycopg 3 connection pool.
- Kept migrations explicit. PostgreSQL app startup checks for `alembic_version` and fails with migration instructions rather than making schema changes automatically.
- Added an initial Alembic schema and PostgreSQL 16 CI job. A schema migration does not copy data from an existing SQLite file.
- Preserved transaction reference and file SHA-256 uniqueness. A transaction-scoped advisory lock serializes PostgreSQL file ingestion; a second transaction-scoped advisory lock prevents audit-chain forks.
- Added indexes for transaction creation time, normalized name, risk classification, and audit hash. Transaction reference and audit event lookups already use primary/unique indexes; screening status uses the unique transaction foreign key.

## Verification performed

- Baseline before edits: `python -m unittest discover -v` — **57 passed, 0 failed, 0 skipped**.
- V3 full suite: `python -m unittest discover -v` — **57 passed, 0 failed, 4 skipped**. All four skips identify unavailable PostgreSQL integration infrastructure.
- `python -m compileall -q app.py main.py watchlistguard tests migrations` — passed.
- `git diff --check` — passed.
- `alembic history` and `alembic upgrade head --sql` — passed; generated SQL inspected for the initial migration.
- `pg_isready` — PostgreSQL server unavailable in this environment. PostgreSQL runtime, integration, concurrency, reconnect, and EXPLAIN measurements therefore remain unverified here. CI is configured to run the opt-in tests against an isolated PostgreSQL 16 service.
- No Render database was accessed, migrated, or modified. No performance result is claimed.

## Limitations

- SQLite-to-PostgreSQL data transfer is not implemented; the initial migration only establishes the schema.
- PostgreSQL integration and query-plan checks require a disposable PostgreSQL server. The tests report `NOT RUN` when `TEST_POSTGRES_URL` is unset.
- GitHub Actions results are not available until the branch is pushed and CI runs.
