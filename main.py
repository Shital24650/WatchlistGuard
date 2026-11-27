#!/usr/bin/env python3
"""WatchlistGuard command-line interface."""
import argparse
from getpass import getpass
import sys
from watchlistguard.db import begin_admin_write, connect, initialize, seed_watchlist
from watchlistguard.ingestion import ingest_csv, IngestionError
from watchlistguard.service import screen_pending, report_rows
from watchlistguard.audit import verify_chain
from watchlistguard.auth import create_user
from watchlistguard.audit import log_event

def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic transaction screening demonstration")
    parser.add_argument("--db", default=None, help="SQLite path or PostgreSQL URL (defaults to WATCHLISTGUARD_DATABASE_URL / WATCHLISTGUARD_DB)")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Validate and ingest a CSV file"); ingest.add_argument("csv_file")
    sub.add_parser("screen", help="Screen pending transactions")
    sub.add_parser("report", help="Show screening report")
    sub.add_parser("audit-verify", help="Verify SHA-256 audit chain")
    sub.add_parser("create-admin", help="Bootstrap an administrator if none is active")
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        initialize(conn); seed_watchlist(conn)
        if args.command == "create-admin":
            password = getpass("New administrator password (12+ chars): ")
            confirmation = getpass("Confirm password: ")
            if password != confirmation:
                raise ValueError("Passwords do not match.")
            with conn:
                begin_admin_write(conn)
                active_admins = conn.execute(
                    "SELECT COUNT(*) FROM app_users WHERE role='ADMINISTRATOR' AND active=?", (True,)
                ).fetchone()[0]
                if active_admins:
                    raise ValueError("An active administrator already exists; use administrator user management.")
                user = create_user(conn, input("Administrator username: "), password, "ADMINISTRATOR")
                log_event(conn, "USER_CREATED", f"user_id={user['id']}; role=ADMINISTRATOR; bootstrap=true")
            print(f"Administrator created: {user['username']}")
        elif args.command == "ingest":
            result = ingest_csv(conn, args.csv_file)
            print("Ingestion:", ", ".join(f"{k}={v}" for k, v in result.items()))
        elif args.command == "screen":
            print(f"Screened {screen_pending(conn)} pending transaction(s).")
        elif args.command == "report":
            rows = report_rows(conn)
            print("REF | CUSTOMER | AMOUNT | RISK | SCORE | MATCH")
            for row in rows:
                print(f"{row['transaction_ref']} | {row['customer_name']} | {row['currency']} {row['amount']:.2f} | {row['risk_level']} | {row['risk_score']} | {row['match_type']}")
            print(f"Total: {len(rows)} transaction(s).")
        elif args.command == "audit-verify":
            ok, message = verify_chain(conn); print(message)
            if not ok: return 2
        return 0
    except (IngestionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1
    finally:
        conn.close()

if __name__ == "__main__":
    raise SystemExit(main())
