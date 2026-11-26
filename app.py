"""Flask dashboard for the synthetic WatchlistGuard demonstration."""
import hashlib
import os
import secrets
import tempfile
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from watchlistguard.audit import verify_chain, log_event
from watchlistguard.db import connect, initialize, seed_watchlist
from watchlistguard.ingestion import IngestionError, ingest_csv
from watchlistguard.service import report_rows, screen_pending

MAX_UPLOAD_BYTES = 1024 * 1024


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("WATCHLISTGUARD_DB", "data/watchlistguard.db"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    )
    if test_config:
        app.config.update(test_config)

    def database():
        conn = connect(app.config["DATABASE"])
        initialize(conn)
        seed_watchlist(conn)
        return conn

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        flash("Upload rejected: CSV files must be 1 MB or smaller.", "error")
        return redirect(url_for("dashboard")), 303

    @app.get("/health")
    def health():
        try:
            conn = database()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return {"status": "ok"}, 200
        except Exception:
            return {"status": "unavailable"}, 503

    @app.get("/")
    def dashboard():
        conn = database()
        try:
            summary = {
                "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
                "screened": conn.execute("SELECT COUNT(*) FROM screening_results").fetchone()[0],
                "high": conn.execute(
                    "SELECT COUNT(*) FROM screening_results WHERE risk_level = ?", ("HIGH",)
                ).fetchone()[0],
                "pending": conn.execute(
                    """SELECT COUNT(*) FROM transactions t
                       LEFT JOIN screening_results s ON s.transaction_id=t.id
                       WHERE s.id IS NULL"""
                ).fetchone()[0],
            }
            rows = report_rows(conn)
            activity = conn.execute(
                "SELECT timestamp,event_type,details FROM audit_logs ORDER BY event_id DESC LIMIT 8"
            ).fetchall()
            audit_ok, audit_message = verify_chain(conn)
            return render_template(
                "dashboard.html", summary=summary, rows=rows, activity=activity,
                audit_ok=audit_ok, audit_message=audit_message,
            )
        finally:
            conn.close()

    @app.post("/upload")
    def upload():
        upload_file = request.files.get("file")
        if upload_file is None or not upload_file.filename:
            flash("Choose a CSV file to upload.", "error")
            return redirect(url_for("dashboard"))
        filename = secure_filename(upload_file.filename)
        if not filename or Path(filename).suffix.lower() != ".csv":
            flash("Only files with a .csv extension are accepted.", "error")
            return redirect(url_for("dashboard"))
        raw = upload_file.stream.read(MAX_UPLOAD_BYTES + 1)
        if not raw:
            flash("The selected CSV file is empty.", "error")
            return redirect(url_for("dashboard"))
        if len(raw) > MAX_UPLOAD_BYTES:
            flash("Upload rejected: CSV files must be 1 MB or smaller.", "error")
            return redirect(url_for("dashboard"))
        temp_path = None
        conn = database()
        try:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as temp:
                temp.write(raw)
                temp_path = temp.name
            result = ingest_csv(conn, temp_path)
            conn.execute(
                "UPDATE processed_files SET file_name = ? WHERE sha256 = ?",
                (filename, hashlib.sha256(raw).hexdigest()),
            )
            conn.commit()
            flash(
                "CSV processed: " + ", ".join(f"{key}={value}" for key, value in result.items()),
                "success",
            )
        except (IngestionError, OSError, UnicodeError, ValueError):
            conn.rollback()
            flash("The CSV could not be processed. Check its format and required columns.", "error")
        except Exception:
            conn.rollback()
            app.logger.exception("Unexpected upload processing error")
            flash("The upload could not be completed. Please try again.", "error")
        finally:
            conn.close()
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        return redirect(url_for("dashboard"))

    @app.post("/screen")
    def screen():
        conn = database()
        try:
            count = screen_pending(conn)
            flash(f"Screening completed. {count} pending transaction(s) processed.", "success")
        except Exception:
            conn.rollback()
            app.logger.exception("Screening action failed")
            flash("Screening could not be completed. Please try again.", "error")
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    @app.post("/audit/verify")
    def audit_verify():
        conn = database()
        try:
            ok, message = verify_chain(conn)
            with conn:
                log_event(conn, "AUDIT_VERIFY", "result=" + ("ok" if ok else "failed"))
            flash(
                message if ok else "Audit verification failed. Review the audit history.",
                "success" if ok else "error",
            )
        except Exception:
            conn.rollback()
            app.logger.exception("Audit verification action failed")
            flash("Audit verification could not be completed.", "error")
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
