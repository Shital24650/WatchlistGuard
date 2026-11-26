"""Flask dashboard and JSON API for the synthetic WatchlistGuard demo."""
import os
import secrets
import tempfile
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from watchlistguard.audit import verify_chain, log_event
from watchlistguard.db import connect, initialize, seed_watchlist
from watchlistguard.ingestion import IngestionError, ingest_csv
from watchlistguard.service import report_rows, report_page, screen_pending
from watchlistguard.openapi import openapi_document

MAX_UPLOAD_BYTES = 1024 * 1024


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("WATCHLISTGUARD_DB", "data/watchlistguard.db"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 64 * 1024,
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
            "default-src 'self'; script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Upload exceeds the 1 MB file limit."}), 413
        flash("Upload rejected: CSV files must be 1 MB or smaller.", "error")
        return redirect(url_for("dashboard")), 303

    def process_upload(upload_file):
        if upload_file is None or not upload_file.filename:
            return None, ("A CSV file is required in the 'file' field.", 400)
        filename = secure_filename(upload_file.filename)
        if not filename or Path(filename).suffix.lower() != ".csv":
            return None, ("Only files with a .csv extension are accepted.", 400)
        raw = upload_file.stream.read(MAX_UPLOAD_BYTES + 1)
        if not raw:
            return None, ("The selected CSV file is empty.", 400)
        if len(raw) > MAX_UPLOAD_BYTES:
            return None, ("Upload rejected: CSV files must be 1 MB or smaller.", 413)

        temp_path = None
        conn = None
        try:
            conn = database()
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as temp:
                temp.write(raw)
                temp_path = temp.name
            result = ingest_csv(conn, temp_path, source_name=filename)
            return result, None
        except (IngestionError, OSError, UnicodeError, ValueError):
            if conn is not None:
                conn.rollback()
            return None, ("CSV could not be processed. Check its format and required columns.", 400)
        except Exception:
            if conn is not None:
                conn.rollback()
            app.logger.exception("Unexpected upload processing error")
            return None, ("Upload could not be completed. Please try again.", 500)
        finally:
            if conn is not None:
                conn.close()
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    app.logger.warning("Could not remove temporary upload file")

    @app.get("/health")
    def health():
        try:
            conn = database()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return {"status": "ok"}, 200
        except Exception:
            app.logger.exception("Health check failed")
            return {"status": "unavailable"}, 503

    @app.get("/api/openapi.json")
    def openapi_json():
        return jsonify(openapi_document())

    @app.get("/api/docs")
    def api_docs():
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WatchlistGuard API documentation</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="/static/swagger-init.js"></script>
</body>
</html>"""

    @app.post("/api/upload")
    def api_upload():
        result, error = process_upload(request.files.get("file"))
        if error:
            message, status = error
            return jsonify({"error": message}), status
        return jsonify({"message": "CSV processed.", **result}), 200

    @app.post("/api/screen")
    def api_screen():
        conn = database()
        try:
            count = screen_pending(conn)
            return jsonify({"message": "Screening completed.", "screened": count}), 200
        except Exception:
            conn.rollback()
            app.logger.exception("API screening failed")
            return jsonify({"error": "Screening could not be completed."}), 500
        finally:
            conn.close()

    @app.get("/api/report")
    def api_report():
        def query_integer(name, default, minimum, maximum=None):
            raw_value = request.args.get(name)
            if raw_value is None:
                return default
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be an integer.")
            if value < minimum or (maximum is not None and value > maximum):
                limit = f" and at most {maximum}" if maximum is not None else ""
                raise ValueError(f"{name} must be at least {minimum}{limit}.")
            return value

        try:
            page = query_integer("page", 1, 1)
            page_size = query_integer("page_size", 20, 1, 100)
            risk_level = request.args.get("risk_level")
            if risk_level is not None:
                risk_level = risk_level.strip().upper()
                if risk_level not in {"PENDING", "LOW", "MEDIUM", "HIGH"}:
                    raise ValueError("risk_level must be PENDING, LOW, MEDIUM, or HIGH.")
            screening_status = request.args.get("screening_status")
            if screening_status is not None:
                screening_status = screening_status.strip().upper()
                if screening_status not in {"PENDING", "SCREENED"}:
                    raise ValueError("screening_status must be PENDING or SCREENED.")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        conn = database()
        try:
            total, rows = report_page(conn, page, page_size, risk_level, screening_status)
            total_pages = (total + page_size - 1) // page_size
            return jsonify({
                "count": total,
                "results": [dict(row) for row in rows],
                "pagination": {
                    "page": page, "page_size": page_size,
                    "total": total, "total_pages": total_pages,
                },
            }), 200
        except Exception:
            app.logger.exception("API report failed")
            return jsonify({"error": "Report could not be generated."}), 500
        finally:
            conn.close()

    @app.post("/api/audit/verify")
    def api_audit_verify():
        conn = database()
        try:
            ok, message = verify_chain(conn)
            with conn:
                log_event(conn, "AUDIT_VERIFY", "result=" + ("ok" if ok else "failed"))
            return jsonify({"valid": ok, "message": message}), (200 if ok else 409)
        except Exception:
            conn.rollback()
            app.logger.exception("API audit verification failed")
            return jsonify({"error": "Audit verification could not be completed."}), 500
        finally:
            conn.close()

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
        result, error = process_upload(request.files.get("file"))
        if error:
            message, _status = error
            flash(message, "error")
        else:
            flash(
                "CSV processed: " + ", ".join(f"{key}={value}" for key, value in result.items()),
                "success",
            )
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
