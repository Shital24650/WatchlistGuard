# WatchlistGuard

**Financial Crime Transaction Screening & Audit Platform**

<p align="center">
  <strong>A security-focused backend engineering project demonstrating transaction screening, database reliability, access control, audit integrity and performance optimization.</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.x-000000?logo=flask">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-Supported-003B57?logo=sqlite">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker">
  <img alt="GitHub Actions" src="https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white">
  <img alt="Security" src="https://img.shields.io/badge/Security-RBAC%20%7C%20CSRF%20%7C%20Scrypt-167D5A">
  <img alt="API" src="https://img.shields.io/badge/API-OpenAPI%203.0.3-85EA2D">
</p>

---

## Project at a glance

| Attribute | Details |
|---|---|
| Project | WatchlistGuard |
| Category | Financial Crime Technology / Backend Engineering |
| Backend | Python, Flask |
| Databases | SQLite, PostgreSQL |
| API documentation | OpenAPI 3.0.3, Swagger UI |
| Security | Scrypt, RBAC, CSRF, secure sessions |
| Audit mechanism | SHA-256 hash chain |
| Database migrations | Alembic |
| Testing | Python unittest, PostgreSQL integration tests |
| CI/CD | GitHub Actions |
| Containerization | Docker, Docker Compose |
| Load testing | Locust |
| Deployment demonstration | Render |

**Repository:** https://github.com/Shital24650/WatchlistGuard

> **DEMONSTRATION ONLY — SYNTHETIC DATA.** This project is an educational engineering prototype. It is not connected to banking infrastructure, real sanctions lists, financial institutions or regulatory authorities. It is not a production AML system and must not be used to make real financial or compliance decisions.

---

## 1. Overview

WatchlistGuard is a Python-based transaction-screening application designed to demonstrate backend engineering practices relevant to financial technology, compliance operations and risk systems.

The application accepts synthetic transaction records, validates and ingests CSV files, compares customer or entity names against a fictional watchlist, calculates transparent risk scores, and produces screening reports.

The project goes beyond basic transaction matching by implementing supporting engineering capabilities:

- Secure user authentication and role-based authorization.
- Transaction-safe and idempotent CSV ingestion.
- SQLite and PostgreSQL database support.
- Connection pooling and PostgreSQL transaction coordination.
- SHA-256 hash-chained audit records.
- REST API with OpenAPI documentation.
- SQL-level report pagination and filtering.
- Cursor-based keyset pagination.
- Database migrations and query optimization.
- Structured application logging and health checks.
- Docker-based deployment configuration.
- Automated testing and CI validation.
- Reproducible synthetic performance benchmarks.

The engineering objective is to demonstrate how a backend system can be designed around security, traceability, data integrity, reliability and maintainability.

## 2. Problem and engineering approach

Transaction screening workflows require more than comparing two names.

A reliable application also needs to handle:

1. Data ingestion and validation.
2. Duplicate transaction prevention.
3. Transparent screening and risk classification.
4. Controlled access to application operations.
5. Traceable user and system activity.
6. Consistent database behavior.
7. Efficient retrieval of screening results.
8. Automated regression and security testing.

WatchlistGuard addresses these concerns through a modular Python application with separate database, authentication, screening, ingestion, audit and service components.

## 3. System architecture

The following diagram represents the implemented application structure.

```mermaid
flowchart TB
    subgraph CLIENT["Presentation Layer"]
        UI["Flask Web Dashboard"]
        API_CLIENT["REST API Clients"]
        CLI["Python CLI"]
    end

    subgraph APP["Application Layer"]
        FLASK["Flask Application<br/>app.py"]
        AUTH["Authentication & RBAC<br/>auth.py"]
        ROUTES["Dashboard & API Routes"]
        OBS["Request Logging<br/>Health & Readiness"]
    end

    subgraph SERVICES["Business Logic Layer"]
        INGEST["CSV Ingestion<br/>ingestion.py"]
        SCREEN["Screening Engine<br/>screening.py"]
        SERVICE["Application Services<br/>service.py"]
        AUDIT["Audit Service<br/>audit.py"]
    end

    subgraph DATA["Data Access Layer"]
        DB["Dialect-aware DB Adapter<br/>db.py"]
        POOL["Psycopg 3<br/>Connection Pool"]
        MIG["Alembic Migrations"]
    end

    subgraph STORAGE["Persistence Layer"]
        SQLITE[("SQLite")]
        POSTGRES[("PostgreSQL")]
    end

    UI --> FLASK
    API_CLIENT --> FLASK
    CLI --> SERVICE

    FLASK --> ROUTES
    FLASK --> AUTH
    FLASK --> OBS

    ROUTES --> INGEST
    ROUTES --> SCREEN
    ROUTES --> SERVICE
    ROUTES --> AUDIT

    INGEST --> DB
    SCREEN --> SERVICE
    SERVICE --> DB
    AUDIT --> DB

    DB --> SQLITE
    DB --> POOL
    POOL --> POSTGRES
    MIG -.-> POSTGRES
```

### Architectural responsibilities

| Component | Responsibility |
|---|---|
| `app.py` | Flask application, web routes, REST API, authentication integration and observability |
| `auth.py` | Password hashing, authentication, session user resolution and role enforcement |
| `ingestion.py` | CSV parsing, validation, file fingerprints and transaction deduplication |
| `screening.py` | Name normalization, similarity matching and risk classification |
| `service.py` | Screening orchestration and report queries |
| `audit.py` | Audit event creation and hash-chain verification |
| `db.py` | SQLite connections, PostgreSQL adapter, pooling and database initialization |
| `openapi.py` | OpenAPI API contract |
| `main.py` | Command-line interface |
| `migrations/` | Version-controlled PostgreSQL schema migrations |

The architecture separates HTTP handling from business logic and database access, making individual components easier to test and maintain.

## 4. Core functionality

### 4.1 Transaction ingestion

The application accepts CSV files with the following required columns:

```csv
transaction_ref,customer_name,amount,currency
SYN-1001,Amina Rahman,1250.00,USD
SYN-1002,Jordan Lee,250.00,INR
```

The ingestion pipeline performs:

- Required-column validation.
- UTF-8 CSV parsing.
- Transaction-reference validation.
- Positive and finite amount validation.
- Currency-format validation.
- File fingerprint generation using SHA-256.
- Duplicate transaction detection.
- Atomic database writes.
- Audit event creation.

#### Idempotency design

Two levels of duplicate prevention are implemented:

1. Identical file contents are detected using SHA-256 fingerprints and skipped.
2. Changed files are processed row by row, with the unique `transaction_ref` constraint preventing duplicate transaction insertion.

A repeated upload does not needlessly recreate the same transaction records.

The ingestion response reports:

| Field | Meaning |
|---|---|
| `inserted` | Successfully inserted transactions |
| `rejected` | Invalid rows |
| `duplicates` | Existing transaction references |
| `skipped_file` | Whether an identical file was skipped |

The web upload is restricted to CSV files with a maximum configured size of 1 MB.

### 4.2 Screening engine

The screening engine is implemented in `watchlistguard/screening.py`.

It performs:

1. Case normalization.
2. Punctuation and whitespace normalization.
3. Exact name comparison.
4. Approximate similarity comparison.
5. Risk-score calculation.
6. Risk classification.
7. Explanation generation.

The approximate matching implementation uses Python's `difflib.SequenceMatcher`.

The approximate-match threshold is `0.82`.

The risk score is calculated from the configured synthetic watchlist weight and name similarity.

```python
score = min(
    100,
    round(
        watchlist_weight *
        (1.0 if match_type == "EXACT" else similarity)
    )
)
```

Risk classification:

| Score | Classification |
|---|---|
| 0–34 | LOW |
| 35–74 | MEDIUM |
| 75–100 | HIGH |

Each screening result includes the match type, similarity, score, risk band and explanation.

> **Important:** This is a transparent demonstration algorithm, not a validated sanctions-matching model. Similarity alone cannot establish identity or determine whether a person is sanctioned.

### 4.3 Reporting and pagination

The application provides two report retrieval strategies.

#### Offset-based pagination

`GET /api/report`

- Supports page numbers.
- Supports configurable page sizes.
- Supports risk-level filtering.
- Supports screening-status filtering.
- Returns total matching record counts.
- Preserves a conventional page-based response contract.

#### Cursor-based pagination

`GET /api/report/cursor`

- Uses transaction IDs as continuation cursors.
- Fetches a bounded result set.
- Avoids deep SQL offsets.
- Avoids a full matching-record count.
- Returns continuation information through `next_after_id` and `has_more`.

Both endpoints cap the page size at 100 records.

The cursor endpoint is useful when clients need to traverse larger result sets without repeatedly requesting deep offset pages.

## 5. Security architecture

Security controls are implemented across authentication, authorization, request validation and operational logging.

### Authentication

- Password hashing with Werkzeug scrypt.
- Server-side user records.
- Signed Flask sessions.
- Session rotation after successful login.
- 30-minute default session lifetime.
- HttpOnly session cookies.
- SameSite=Lax cookie configuration.
- Secure cookies in production.
- Login-attempt throttling.
- No default administrator credentials.

Administrator bootstrap is performed through an explicit CLI command:

```bash
python main.py create-admin
```

The command prompts for a username and password and refuses to create another administrator when an active administrator already exists.

### Role-based access control

Three application roles are implemented:

| Role | Access purpose |
|---|---|
| `ADMINISTRATOR` | Administrative operations, user management and privileged workflows |
| `ANALYST` | Screening and operational result access |
| `AUDITOR` | Read-oriented access to screening results and audit records |

Role enforcement is performed server-side rather than relying only on frontend visibility.

The implementation also protects the last active administrator from being demoted.

### Request protection

Implemented security controls include:

- CSRF token validation for unsafe HTTP methods.
- Input validation.
- Secure filename handling.
- CSV file extension and size validation.
- Parameterized SQL queries.
- Jinja template autoescaping.
- Generic API error responses.
- Content Security Policy.
- `X-Content-Type-Options`.
- `X-Frame-Options`.
- Referrer Policy.
- Permissions Policy.
- Cache-Control protections.
- HTTP Strict Transport Security for secure/production requests.

### Security limitation

Login throttling and administrator-adjustable application settings are process-local. A multi-worker production deployment would require shared storage or distributed coordination for these controls.

## 6. Tamper-evident audit logging

Audit logging is implemented in `watchlistguard/audit.py`.

Every audit event contains:

- Event identifier.
- UTC timestamp.
- Event type.
- Event details.
- Previous event hash.
- Current event hash.

The current hash is generated using SHA-256 over a deterministic JSON representation of the event data.

```mermaid
flowchart TD
    A["Genesis Hash"] --> B["Audit Event 1"]
    B --> C["SHA-256 Hash 1"]
    C --> D["Audit Event 2 + Previous Hash"]
    D --> E["SHA-256 Hash 2"]
    E --> F["Audit Event 3 + Previous Hash"]
    F --> G["SHA-256 Hash 3"]
```

### Verification process

The verification function:

1. Reads audit events in event order.
2. Reconstructs the expected digest.
3. Checks the previous-hash relationship.
4. Checks the current event hash.
5. Reports the first detected integrity failure.

Audit records cover relevant application activities such as login outcomes, logout, user creation, role changes, settings changes, ingestion, screening and audit verification.

### Concurrent audit writes

The application coordinates audit-chain writes:

- SQLite uses `BEGIN IMMEDIATE` to acquire a write reservation.
- PostgreSQL uses a transaction-scoped advisory lock.

This helps prevent concurrent writers from reading the same chain head and producing competing audit entries.

> **Security boundary:** Hash chaining provides tamper evidence, not absolute immutability. A sufficiently privileged actor who can rewrite the complete database and recompute every hash could alter the chain. Production-grade audit protection would require independently protected storage and external verification.

## 7. Database engineering

WatchlistGuard supports two database engines through a shared database access interface.

| Feature | SQLite | PostgreSQL |
|---|---|---|
| Default backend | Yes | Optional |
| Connection management | Native SQLite connections | Psycopg 3 connection pool |
| Schema initialization | Application-managed | Explicit Alembic migrations |
| Ingestion serialization | `BEGIN IMMEDIATE` | Transaction advisory lock |
| Audit serialization | SQLite write reservation | Transaction advisory lock |
| Foreign keys | Enabled | Enforced |
| Unique transaction references | Yes | Yes |

### PostgreSQL implementation

The PostgreSQL integration includes:

- Psycopg 3.
- Bounded connection pooling.
- Qmark-to-PostgreSQL parameter adaptation.
- Connection lease cleanup.
- Transaction management.
- Pool lifecycle management.
- PostgreSQL-specific integration tests.
- Transaction-scoped advisory locks.

### Database migrations

Alembic migrations are organized as:

| Migration | Purpose |
|---|---|
| `0001_initial` | Initial transaction, watchlist, screening, audit and processed-file schema |
| `0002_app_users` | User authentication and role schema |
| `0003_query_performance` | Report index optimization and removal of redundant indexes |

PostgreSQL migrations are explicitly applied by the operator. The application does not automatically create or migrate a PostgreSQL schema during normal request processing.

SQLite remains the default lightweight development and demonstration backend.

> **Data migration note:** Applying the PostgreSQL schema does not automatically transfer existing SQLite records.

## 8. API documentation

The API contract is generated through `watchlistguard/openapi.py` using OpenAPI 3.0.3.

Interactive documentation is available at:

```text
/api/docs
```

The machine-readable API specification is available at:

```text
/api/openapi.json
```

### API endpoint reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Application and database health |
| GET | `/live` | Application process liveness |
| GET | `/ready` | Database readiness |
| GET | `/api/openapi.json` | OpenAPI specification |
| GET | `/api/docs` | Swagger UI |
| GET | `/api/auth/csrf` | CSRF token retrieval |
| POST | `/api/auth/login` | User authentication |
| POST | `/api/auth/logout` | Session termination |
| POST | `/api/upload` | CSV ingestion |
| POST | `/api/screen` | Screen pending transactions |
| GET | `/api/report` | Filtered and paginated reports |
| GET | `/api/report/cursor` | Cursor-based report retrieval |
| GET | `/api/audit` | Audit record retrieval |
| POST | `/api/audit/verify` | Verify audit integrity |
| GET/POST | `/api/admin/users` | Administrator user management |
| PUT | `/api/admin/users/{id}/role` | Change user role |
| GET/PUT | `/api/admin/settings` | Read and update process-local settings |

Protected operations require an authenticated session. Unsafe requests additionally require the session-bound CSRF token.

## 9. Observability and operational reliability

The project implements operational features beyond basic request handling.

### Structured logging

Application logs use JSON formatting and include:

- UTC timestamps.
- Severity levels.
- Event names.
- Server-generated request IDs.
- HTTP methods.
- Matched application routes.
- Response status codes.
- Request duration.
- Safe error categories.

Sensitive information such as passwords, cookies, authorization headers, database credentials and transaction fields is excluded from application request logs.

The application returns an `X-Request-ID` response header for request correlation.

### Health checks

| Endpoint | Responsibility |
|---|---|
| `/live` | Confirms the application process is responding |
| `/ready` | Checks application and database readiness |
| `/health` | Backward-compatible health endpoint used by the deployment configuration |

The liveness endpoint does not require a database connection. Readiness checks database availability.

## 10. Performance engineering

Performance work focuses on database query execution and bounded result retrieval.

Implemented improvements include:

- Risk-level and transaction-ID composite indexing.
- Removal of unused or redundant indexes.
- SQL-level filtering.
- Bounded report queries.
- Cursor-based keyset pagination.
- Reproducible benchmark scripts.
- Synthetic Locust workloads.

### Benchmark methodology

The repository includes:

```bash
python -m benchmarks.report_benchmark --rows 50000
```

The benchmark:

- Creates a disposable SQLite database.
- Generates 50,000 synthetic transactions.
- Measures legacy and optimized report paths.
- Uses five warm-up iterations.
- Collects 40 timed samples.
- Compares p50, p95 and p99 latency.
- Checks result equivalence.
- Captures SQLite query plans.

### Recorded local benchmark

The following measurements are recorded in the project README for the development environment.

| Operation | Legacy p50 | Optimized p50 |
|---|---|---|
| Filtered first-page report | 27.181 ms | 4.702 ms |
| Deep-page report | 49.227 ms | 0.117 ms |

The first comparison is between the legacy filtered query and the optimized report endpoint. The deep-page comparison is between the legacy exact-count/offset approach and cursor-based pagination.

> These are recorded local synthetic SQLite measurements, not production performance guarantees. Actual performance depends on hardware, database configuration, workload and deployment conditions.

### Load testing

Locust is included as an optional workload tool.

The workload exercises:

- Authentication and CSRF.
- Standard report retrieval.
- Filtered report retrieval.
- Cursor pagination.
- Batch CSV ingestion.
- Screening.
- Audit retrieval.

Load tests require a disposable environment and dedicated test credentials. Production accounts and real customer data must never be used.

## 11. Testing and CI

The repository includes automated tests for application functionality, security, database behavior and integration contracts.

### Testing coverage

| Area | Test focus |
|---|---|
| CLI | Ingestion, screening, reporting and audit verification |
| Ingestion | CSV validation, duplicate handling and idempotency |
| Screening | Name matching and risk classification |
| API | Request validation, response contracts and pagination |
| Authentication | Password hashing, login and session behavior |
| Authorization | Role permissions and administrator invariants |
| CSRF | Unsafe request protection |
| Audit | Hash verification and concurrent appends |
| SQLite | Reliability and concurrency |
| PostgreSQL | Migrations, pooling and transaction behavior |
| Observability | Logging, health checks and safe errors |
| OpenAPI | API contract validation |

### GitHub Actions pipeline

The workflow in `.github/workflows/tests.yml` contains four jobs:

1. **Unit and security validation**
   - Python compilation.
   - Complete unittest suite.
   - Security-specific tests.
   - Bandit static analysis.
   - Dependency vulnerability auditing.
   - OpenAPI contract validation.

2. **PostgreSQL integration**
   - PostgreSQL 16 service.
   - Alembic migration execution.
   - Migration downgrade and upgrade.
   - PostgreSQL integration tests.

3. **Docker build**
   - Production container image build.

4. **Load-test tool validation**
   - Locust source compilation.
   - Workload discovery.
   - Optional dependency security audit.

### Run tests locally

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the full test suite:

```bash
python -m unittest discover -v
```

Run the security tests separately:

```bash
python -m unittest tests.test_security -v
```

Run PostgreSQL integration tests against a disposable PostgreSQL database:

```bash
export TEST_POSTGRES_URL="postgresql://USER:PASSWORD@HOST:5432/TEST_DB"

python -m unittest \
  tests.test_postgres_integration \
  tests.test_security_postgres -v
```

> Never point integration tests at a production database.

## 12. Technology stack

| Layer | Technology |
|---|---|
| Programming language | Python |
| Web framework | Flask |
| WSGI server | Gunicorn |
| Database | SQLite, PostgreSQL |
| PostgreSQL driver | Psycopg 3 |
| Connection pooling | Psycopg Pool |
| Schema migrations | Alembic |
| API specification | OpenAPI 3.0.3 |
| API interface | Swagger UI |
| Authentication | Werkzeug scrypt, Flask sessions |
| Authorization | Role-based access control |
| Audit integrity | SHA-256 |
| Automated testing | Python unittest |
| Security analysis | Bandit, pip-audit |
| API validation | openapi-spec-validator |
| Load testing | Locust |
| Containerization | Docker, Docker Compose |
| CI | GitHub Actions |
| Hosting demonstration | Render |

## 13. Repository structure

```text
WatchlistGuard/
│
├── .github/
│   └── workflows/
│       └── tests.yml
│
├── benchmarks/
│   └── report_benchmark.py
│
├── data/
│   └── transactions.csv
│
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_app_users.py
│       └── 0003_query_performance.py
│
├── scripts/
│   ├── ingest.sh
│   └── run_screening.sh
│
├── static/
│   ├── styles.css
│   └── swagger-init.js
│
├── templates/
│   ├── dashboard.html
│   └── login.html
│
├── tests/
│   ├── security_client.py
│   ├── test_api.py
│   ├── test_api_contract.py
│   ├── test_cli_regression.py
│   ├── test_db_pool.py
│   ├── test_ingestion_source_name.py
│   ├── test_observability.py
│   ├── test_postgres_integration.py
│   ├── test_reliability_sqlite.py
│   ├── test_security.py
│   ├── test_security_postgres.py
│   ├── test_watchlistguard.py
│   └── test_web.py
│
├── watchlistguard/
│   ├── __init__.py
│   ├── auth.py
│   ├── audit.py
│   ├── db.py
│   ├── ingestion.py
│   ├── openapi.py
│   ├── screening.py
│   └── service.py
│
├── app.py
├── main.py
├── container_entrypoint.py
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── locustfile.py
├── requirements.txt
├── requirements-dev.txt
├── requirements-load.txt
├── requirements.lock
├── render.yaml
├── V3_IMPLEMENTATION_REPORT.md
├── V4_IMPLEMENTATION_REPORT.md
└── README.md
```

## 14. Local installation and execution

### Prerequisites

- Python 3.9 or later.
- Git.
- pip.

### Clone the repository

```bash
git clone https://github.com/Shital24650/WatchlistGuard.git
cd WatchlistGuard
```

### Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Linux / macOS**

```bash
source .venv/bin/activate
```

**Windows**

```powershell
.venv\Scripts\activate
```

### Install dependencies

```bash
python -m pip install -r requirements.txt
```

### Configure the application

**Linux / macOS:**

```bash
export FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export WATCHLISTGUARD_DB="data/watchlistguard-local.db"
```

**Windows PowerShell:**

```powershell
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
$env:WATCHLISTGUARD_DB = "data/watchlistguard-local.db"
```

### Start the application

```bash
flask --app app run --host 127.0.0.1 --port 5000
```

Open:

```text
http://127.0.0.1:5000
```

API documentation:

```text
http://127.0.0.1:5000/api/docs
```

The local SQLite database is initialized automatically.

### Bootstrap an administrator

In another terminal, from the repository root:

```bash
python main.py create-admin
```

Follow the interactive prompts. Use a unique username and a password of at least 12 characters.

### Run the CLI workflow

Ingest synthetic transactions:

```bash
python main.py ingest data/transactions.csv
```

Screen pending transactions:

```bash
python main.py screen
```

View the report:

```bash
python main.py report
```

Verify audit integrity:

```bash
python main.py audit-verify
```

## 15. PostgreSQL configuration

Set the PostgreSQL connection URL:

```bash
export WATCHLISTGUARD_DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE"
```

PostgreSQL takes precedence over `WATCHLISTGUARD_DB`.

Apply migrations explicitly:

```bash
alembic upgrade head
```

Optional connection pool configuration:

```bash
export WATCHLISTGUARD_DB_POOL_SIZE=5
export WATCHLISTGUARD_DB_POOL_TIMEOUT=5
```

The application requires an already migrated PostgreSQL schema. It does not automatically migrate PostgreSQL when a request arrives.

For production or shared databases, migration execution should follow an approved backup and change-management process.

## 16. Docker deployment

Docker Compose starts the application and PostgreSQL.

Prepare the environment files:

```bash
cp .env.example .env
cp .app.env.example .app.env
```

Populate the required private values before starting the stack.

Build the image:

```bash
docker compose build
```

Apply the database migrations:

```bash
docker compose run --rm app alembic upgrade head
```

Start the services:

```bash
docker compose up --wait
```

Open:

```text
http://127.0.0.1:5000
```

The Compose configuration includes:

- PostgreSQL 16.
- Named database volume.
- Application health checks.
- PostgreSQL health checks.
- Environment-based configuration.
- Graceful application shutdown.

The production Dockerfile uses a multi-stage build, pinned Python base image, locked runtime dependencies and a non-root application user.

## 17. Engineering decisions and trade-offs

| Decision | Reason |
|---|---|
| SQLite as default | Simple, lightweight development and demo setup |
| PostgreSQL integration | Demonstrates relational database and concurrency engineering |
| Explicit Alembic migrations | Controlled schema evolution |
| Scrypt password hashing | Secure password storage |
| Server-side RBAC | Enforce permissions independently of the UI |
| CSRF tokens | Protect unsafe session-authenticated requests |
| SHA-256 hash chaining | Detect changes to audit history |
| Unique transaction references | Enforce transaction-level deduplication |
| File fingerprints | Prevent repeated processing of identical uploads |
| Connection pooling | Reuse PostgreSQL connections |
| Advisory locks | Coordinate selected concurrent PostgreSQL writes |
| Cursor pagination | Avoid deep-offset traversal costs |
| Structured logs | Improve operational diagnosis |
| Separate liveness/readiness | Distinguish process availability from database readiness |
| Docker | Improve deployment consistency |

## 18. Known limitations and future improvements

WatchlistGuard is an educational portfolio project. It deliberately does not claim to provide the guarantees of a production financial institution.

Potential future engineering improvements include:

- More advanced entity resolution and explainable matching.
- Configurable screening thresholds.
- Independent audit-log archival.
- Distributed rate limiting.
- Shared configuration and settings storage.
- Metrics and distributed tracing.
- Production-grade secret management.
- Formal threat modeling and independent penetration testing.
- More extensive performance testing across database engines.
- Secure, independently verified backup and recovery workflows.

## 19. Responsible use

All supplied transaction and watchlist records are synthetic.

Do not upload real customer data, personal information, account numbers, payment details or banking records.

Screening outcomes are illustrative and must not be interpreted as real sanctions matches, financial-crime determinations or regulatory compliance decisions.

---

## 20. Author

**Shital Parab**

Software Engineering | Backend Systems | Database Engineering | Security & Test Automation

- GitHub: https://github.com/Shital24650
- Repository: https://github.com/Shital24650/WatchlistGuard

---

<p align="center">
  <strong>WatchlistGuard</strong><br>
  Engineering secure, auditable and reliable transaction-screening workflows.
</p>
