# WatchlistGuard

WatchlistGuard is a lightweight Python transaction-screening portfolio project. It demonstrates CSV ingestion and validation, duplicate prevention, transparent synthetic watchlist matching, SQLite persistence, Bash automation, unit testing, and SHA-256 hash-chained audit events.

> **Scope:** Educational prototype using synthetic data only. It is not a production AML, sanctions-screening, or banking compliance system; it has no regulatory certification and must not be used to make real customer or payment decisions.

## Requirements and installation

- Python 3.9 or newer
- Bash for the automation scripts (Linux, macOS, or Termux)
- No third-party Python packages are required.

```bash
git clone https://github.com/Shital24650/WatchlistGuard.git
cd WatchlistGuard
python3 --version
python3 -m unittest discover -v
```

The application creates `data/watchlistguard.db` on first CLI use. For an isolated run, pass `--db /tmp/watchlistguard-demo.db` before the command.

## CLI

```bash
python3 main.py --db /tmp/watchlistguard-demo.db ingest data/transactions.csv
python3 main.py --db /tmp/watchlistguard-demo.db screen
python3 main.py --db /tmp/watchlistguard-demo.db report
python3 main.py --db /tmp/watchlistguard-demo.db audit-verify
```

The `--db` option is optional; without it, the default database is `data/watchlistguard.db`.

Expected sample-data behavior:

```text
Ingestion: inserted=5, rejected=1, duplicates=0, skipped_file=0
Screened 5 pending transaction(s).
REF | CUSTOMER | AMOUNT | RISK | SCORE | MATCH
TXN-1001 | Amina Rahman | USD 1250.00 | HIGH | 90 | EXACT
TXN-1002 | Amna Rahman | USD 800.00 | HIGH | 86 | APPROXIMATE
TXN-1003 | Jordan Lee | INR 250.00 | LOW | 0 | NONE
TXN-1004 | Victor Mensah | EUR 5200.00 | HIGH | 85 | EXACT
TXN-1005 | Northstar Trading Ltd | GBP 999.99 | HIGH | 75 | EXACT
Total: 5 transaction(s).
Verified 2 audit event(s).
```

A repeated file with identical bytes is skipped using its SHA-256 fingerprint. A different file containing an already-seen transaction reference is counted as a duplicate. Invalid rows are rejected and reported in the ingestion summary. Missing or malformed input returns a non-zero exit code.

## Bash automation

```bash
chmod +x scripts/*.sh
./scripts/ingest.sh data/transactions.csv
./scripts/run_screening.sh
```

The scripts enable strict Bash error handling, log to `logs/`, validate usage, and propagate command failures.

## Architecture

```text
CSV → main.py → ingestion.py → transactions / processed_files
                         │
                         └── audit.py → audit_logs
transactions → service.py → screening.py ← watchlist
                                  │
                                  ▼
                           screening_results
                                  │
                                  ▼
                              report CLI
```

### Folder structure

```text
.
├── .github/workflows/tests.yml  # GitHub Actions unit tests
├── data/transactions.csv        # Fictional sample transactions
├── scripts/                     # Bash ingestion and screening wrappers
├── tests/                       # unittest suite (isolated in-memory DBs)
├── watchlistguard/
│   ├── audit.py                 # SHA-256 audit chain
│   ├── db.py                    # SQLite schema, indexes, seed list
│   ├── ingestion.py             # CSV validation and deduplication
│   ├── screening.py             # Name normalization, similarity, risk score
│   └── service.py               # Screening and report use cases
└── main.py                      # CLI entry point
```

## Screening model

Names are case-folded, punctuation is converted to spaces, and whitespace is collapsed. Exact normalized matches are identified directly. Approximate matching uses Python's `difflib.SequenceMatcher` with a similarity threshold of 0.82.

For a qualifying match, the score is the configured synthetic watchlist weight multiplied by similarity (exact matches use 1.0), rounded to an integer and capped at 100. Bands are LOW (0–34), MEDIUM (35–74), and HIGH (75–100). Explanations include the matched synthetic entry, match type, similarity, weight, and score. This intentionally simple demonstration does not implement aliases, transliteration, date-of-birth/address matching, list updates, or human case review.

## Database and security controls

SQLite tables: `transactions`, `watchlist`, `screening_results`, `audit_logs`, and `processed_files`. The schema uses primary keys, foreign keys, uniqueness/check constraints, and indexes. SQL values are bound through parameterized statements. Ingestion and screening writes use database transactions. The SQL injection test confirms user-controlled values are treated as data rather than SQL syntax.

The audit log stores event ID, UTC timestamp, event type, details, previous record hash, and current record hash. SHA-256 is calculated over canonical JSON including the previous hash. Verification checks both each event digest and its link to the preceding record. This is tamper-evident, not tamper-proof: an attacker able to rewrite the database and recompute the entire chain could defeat it. Production-grade audit systems need independently protected checkpoints and access controls.

## Testing and continuous integration

Run locally:

```bash
python3 -m unittest discover -v
```

GitHub Actions runs the same standard-library test suite on every push and pull request. Workflow: `.github/workflows/tests.yml`.

Tests use in-memory SQLite databases and temporary synthetic CSV files. They cover valid/invalid and malformed CSV input, duplicate handling, exact/approximate matching, risk bands, parameterized-query safety, screening persistence, audit verification, and audit tampering.

## Limitations

- Synthetic sample names and transactions only; never load real customer, bank, or payment data.
- No external APIs, credentials, paid services, or non-standard Python dependencies.
- Not a production AML or sanctions-screening system and not a claim of regulatory compliance or certification.
- No regulatory policy engine, PEP/adverse-media screening, list licensing, transliteration, alias resolution, case management, human review, model validation, or operational resilience controls.
- SQLite is appropriate for this small local demonstration, not a high-throughput multi-user deployment.
- Name similarity is illustrative and requires careful calibration and human review in any real-world context.
