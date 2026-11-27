"""Flask dashboard and JSON API for the synthetic WatchlistGuard demo."""
import os
import secrets
import tempfile
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from pathlib import Path

from flask import (
    Flask, abort, flash, g, has_request_context, jsonify, redirect, render_template,
    request, session, url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from watchlistguard.audit import verify_chain, log_event
from watchlistguard.db import begin_admin_write, close as close_database, connect, initialize, seed_watchlist
from watchlistguard.ingestion import IngestionError, ingest_csv
from watchlistguard.service import report_rows, report_page, screen_pending
from watchlistguard.openapi import openapi_document
from watchlistguard.auth import authenticate, create_user, current_user, login_required, roles_required

MAX_UPLOAD_BYTES = 1024 * 1024
_login_attempts = {}
_login_attempts_lock = Lock()
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_LIMIT = 10


class JsonLogFormatter(logging.Formatter):
    """Emit compact JSON while keeping exception contents out of logs."""

    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


class RequestContextLogFilter(logging.Filter):
    def filter(self, record):
        if has_request_context():
            record.request_id = getattr(g, "request_id", None)
        return True


def _configure_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestContextLogFilter())
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False


def create_app(test_config=None):
    app = Flask(__name__)
    environment = os.environ.get("APP_ENV", "development").strip().lower()
    if environment not in {"development", "testing", "production"}:
        raise RuntimeError("APP_ENV must be development, testing, or production")
    production = bool(os.environ.get("RENDER") or environment == "production")
    configured_secret = os.environ.get("FLASK_SECRET_KEY")
    if production and not configured_secret:
        raise RuntimeError("FLASK_SECRET_KEY is required in production")
    pool_size = os.environ.get("WATCHLISTGUARD_DB_POOL_SIZE", "5")
    try:
        if not 1 <= int(pool_size) <= 50:
            raise ValueError
    except ValueError as exc:
        raise RuntimeError("WATCHLISTGUARD_DB_POOL_SIZE must be an integer from 1 to 50") from exc
    app.config.update(
        APP_ENV=environment,
        TESTING=environment == "testing",
        SECRET_KEY=configured_secret or secrets.token_hex(32),
        DATABASE=os.environ.get("WATCHLISTGUARD_DATABASE_URL") or os.environ.get(
            "WATCHLISTGUARD_DB", "data/watchlistguard.db"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 64 * 1024,
        UPLOAD_MAX_BYTES=MAX_UPLOAD_BYTES,
        SESSION_TIMEOUT_MINUTES=30,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=production or os.environ.get("WATCHLISTGUARD_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        SESSION_REFRESH_EACH_REQUEST=True,
    )
    if test_config:
        app.config.update(test_config)

    _configure_logging(app)

    @app.before_request
    def start_request_observation():
        g.request_id = uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request_observation(response):
        request_id = getattr(g, "request_id", uuid.uuid4().hex)
        response.headers["X-Request-ID"] = request_id
        started = getattr(g, "request_started", time.perf_counter())
        app.logger.info(
            "http_request",
            extra={"request_id": request_id, "method": request.method,
                   "path": request.url_rule.rule if request.url_rule else "unmatched",
                   "status": response.status_code,
                   "duration_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
        return response

    def database():
        conn = connect(app.config["DATABASE"])
        try:
            initialize(conn)
            seed_watchlist(conn)
            return conn
        except Exception:
            try:
                conn.rollback()
            finally:
                close_database(conn)
            raise

    @app.before_request
    def enforce_authentication_and_csrf():
        g.user = current_user()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "CSRF validation failed."}), 400
                abort(400, description="CSRF validation failed.")

    @app.context_processor
    def inject_security_context():
        return {"csrf_token": lambda: session.setdefault("csrf_token", secrets.token_urlsafe(32)),
                "authenticated_user": current_user()}

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.is_secure or production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        limit_bytes = app.config["UPLOAD_MAX_BYTES"]
        limit_mb = (str(limit_bytes // (1024 * 1024)) if limit_bytes % (1024 * 1024) == 0
                    else f"{limit_bytes / (1024 * 1024):.2f}")
        if request.path.startswith("/api/"):
            return jsonify({"error": f"Upload exceeds the {limit_mb} MB file limit."}), 413
        flash(f"Upload rejected: CSV files must be {limit_mb} MB or smaller.", "error")
        return redirect(url_for("dashboard")), 303

    @app.errorhandler(500)
    def unexpected_error(error):
        cause = getattr(error, "original_exception", None) or error
        app.logger.error("unhandled_request_error", extra={"error_type": type(cause).__name__})
        if request.path.startswith("/api/"):
            return jsonify({"error": "An unexpected server error occurred."}), 500
        return error

    def process_upload(upload_file):
        if upload_file is None or not upload_file.filename:
            return None, ("A CSV file is required in the 'file' field.", 400)
        filename = secure_filename(upload_file.filename)
        if not filename or Path(filename).suffix.lower() != ".csv":
            return None, ("Only files with a .csv extension are accepted.", 400)
        upload_limit = app.config["UPLOAD_MAX_BYTES"]
        raw = upload_file.stream.read(upload_limit + 1)
        if not raw:
            return None, ("The selected CSV file is empty.", 400)
        if len(raw) > upload_limit:
            limit_mb = (str(upload_limit // (1024 * 1024)) if upload_limit % (1024 * 1024) == 0
                        else f"{upload_limit / (1024 * 1024):.2f}")
            return None, (f"Upload rejected: CSV files must be {limit_mb} MB or smaller.", 413)

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
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            app.logger.error("upload_processing_failed", extra={"error_type": type(exc).__name__})
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
        conn = None
        try:
            conn = database()
            conn.execute("SELECT 1").fetchone()
            return {"status": "ok"}, 200
        except Exception as exc:
            app.logger.error("readiness_check_failed", extra={"error_type": type(exc).__name__})
            return {"status": "unavailable"}, 503
        finally:
            if conn is not None:
                conn.close()

    @app.get("/live")
    def liveness():
        return {"status": "ok"}, 200

    @app.get("/ready")
    def readiness():
        return health()

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

    @app.get("/api/auth/csrf")
    def csrf_token_endpoint():
        return jsonify({"csrf_token": session.setdefault("csrf_token", secrets.token_urlsafe(32))})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html")
        return perform_login(request.form.get("username"), request.form.get("password"), api=False)

    @app.route("/api/auth/login", methods=["POST"])
    def api_login():
        payload = request.get_json(silent=True) or request.form
        if not hasattr(payload, "get"):
            return jsonify({"error": "Invalid login request."}), 400
        return perform_login(payload.get("username"), payload.get("password"), api=True)

    def perform_login(username, password, api):
        now = time.monotonic()
        client_key = request.remote_addr or "unknown"
        with _login_attempts_lock:
            recent = [stamp for stamp in _login_attempts.get(client_key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
            _login_attempts[client_key] = recent
            if len(recent) >= _LOGIN_LIMIT:
                if api:
                    return jsonify({"error": "Too many login attempts."}), 429
                abort(429)
        conn = database()
        try:
            user = authenticate(conn, username, password)
            with _login_attempts_lock:
                if user:
                    _login_attempts[client_key] = []
                else:
                    _login_attempts.setdefault(client_key, []).append(now)
            with conn:
                log_event(conn, "LOGIN_SUCCESS" if user else "LOGIN_FAILURE",
                          ("user_id=" + str(user["id"])) if user else "credentials rejected")
            if not user:
                if api:
                    return jsonify({"error": "Invalid username or password."}), 401
                flash("Invalid username or password.", "error")
                return render_template("login.html"), 401
            session.clear()  # rotate signed session contents on authentication
            session.permanent = True
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            if api:
                return jsonify({"message": "Authenticated.", "role": user["role"]})
            destination = request.args.get("next", "")
            if not destination.startswith("/") or destination.startswith("//"):
                destination = url_for("dashboard")
            return redirect(destination)
        finally:
            close_database(conn)

    @app.post("/logout")
    @login_required
    def logout():
        conn = database()
        try:
            with conn:
                log_event(conn, "LOGOUT", "user_id=" + str(session.get("user_id")))
        finally:
            close_database(conn)
        session.clear()
        return redirect(url_for("login"))

    @app.post("/api/auth/logout")
    @login_required
    def api_logout():
        conn = database()
        try:
            with conn:
                log_event(conn, "LOGOUT", "user_id=" + str(session.get("user_id")))
        finally:
            close_database(conn)
        session.clear()
        return jsonify({"message": "Logged out."})

    @app.get("/api/admin/users")
    @roles_required("ADMINISTRATOR")
    def api_list_users():
        conn = database()
        try:
            rows = conn.execute("SELECT id,username,role,active,created_at FROM app_users ORDER BY id").fetchall()
            return jsonify({"users": [dict(row) for row in rows]})
        finally:
            close_database(conn)

    @app.get("/api/admin/settings")
    @roles_required("ADMINISTRATOR")
    def api_get_settings():
        return jsonify({"upload_max_bytes": app.config["UPLOAD_MAX_BYTES"],
                        "session_timeout_minutes": app.config["SESSION_TIMEOUT_MINUTES"],
                        "session_cookie_secure": app.config["SESSION_COOKIE_SECURE"]})

    @app.put("/api/admin/settings")
    @roles_required("ADMINISTRATOR")
    def api_update_settings():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not data:
            return jsonify({"error": "Provide one or more supported settings."}), 400
        if set(data) - {"upload_max_bytes", "session_timeout_minutes"}:
            return jsonify({"error": "Unsupported setting."}), 400
        if any(type(value) is not int for value in data.values()):
            return jsonify({"error": "Settings values must be integers."}), 400
        try:
            upload_limit = int(data.get("upload_max_bytes", app.config["UPLOAD_MAX_BYTES"]))
            timeout_minutes = int(data.get("session_timeout_minutes", app.config["SESSION_TIMEOUT_MINUTES"]))
            if not 1024 <= upload_limit <= MAX_UPLOAD_BYTES or not 5 <= timeout_minutes <= 120:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "Upload limit must be 1024–1048576 bytes and timeout 5–120 minutes."}), 400
        app.config["UPLOAD_MAX_BYTES"] = upload_limit
        app.config["MAX_CONTENT_LENGTH"] = upload_limit + 64 * 1024
        app.config["SESSION_TIMEOUT_MINUTES"] = timeout_minutes
        app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=timeout_minutes)
        conn = database()
        try:
            with conn:
                log_event(conn, "SETTINGS_UPDATED", f"upload_max_bytes={upload_limit}; session_timeout_minutes={timeout_minutes}")
        finally:
            close_database(conn)
        return jsonify({"message": "Settings updated for this application process.",
                        "upload_max_bytes": upload_limit, "session_timeout_minutes": timeout_minutes})

    @app.post("/api/admin/users")
    @roles_required("ADMINISTRATOR")
    def api_create_user():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "A JSON user object is required."}), 400
        conn = database()
        try:
            with conn:
                created = create_user(conn, data.get("username"), data.get("password"), data.get("role"))
                log_event(conn, "USER_CREATED", f"user_id={created['id']}; role={created['role']}")
            return jsonify({"id": created["id"], "username": created["username"], "role": created["role"]}), 201
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        except Exception:
            conn.rollback()
            return jsonify({"error": "User could not be created."}), 409
        finally:
            close_database(conn)

    @app.put("/api/admin/users/<int:user_id>/role")
    @roles_required("ADMINISTRATOR")
    def api_update_role(user_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("role"), str):
            return jsonify({"error": "A role string is required."}), 400
        role = data["role"].upper()
        if role not in {"ADMINISTRATOR", "ANALYST", "AUDITOR"}:
            return jsonify({"error": "Invalid role."}), 400
        conn = database()
        try:
            with conn:
                # Serialize the invariant check with all administrator role
                # changes. SQLite takes its write lock; PostgreSQL takes a
                # transaction-scoped advisory lock before counting admins.
                begin_admin_write(conn)
                target = conn.execute("SELECT role,active FROM app_users WHERE id=?", (user_id,)).fetchone()
                if target is None:
                    return jsonify({"error": "User not found."}), 404
                if target["active"] and target["role"] == "ADMINISTRATOR" and role != "ADMINISTRATOR":
                    active_admins = conn.execute(
                        "SELECT COUNT(*) FROM app_users WHERE role='ADMINISTRATOR' AND active=?",
                        (True,),
                    ).fetchone()[0]
                    if active_admins <= 1:
                        raise ValueError("At least one active administrator must remain.")
                cursor = conn.execute("UPDATE app_users SET role=? WHERE id=?", (role, user_id))
                if cursor.rowcount != 1:
                    return jsonify({"error": "User not found."}), 404
                log_event(conn, "USER_ROLE_CHANGED", f"target_user_id={user_id}; role={role}")
            return jsonify({"message": "Role updated."})
        except ValueError as exc:
            conn.rollback()
            return jsonify({"error": str(exc)}), 400
        finally:
            close_database(conn)

    @app.get("/api/audit")
    @roles_required("ADMINISTRATOR", "AUDITOR")
    def api_audit_records():
        conn = database()
        try:
            rows = conn.execute("SELECT event_id,timestamp,event_type,details,previous_hash,current_hash FROM audit_logs ORDER BY event_id DESC LIMIT 100").fetchall()
            return jsonify({"events": [dict(row) for row in rows]})
        finally:
            close_database(conn)

    @app.post("/api/upload")
    @roles_required("ADMINISTRATOR")
    def api_upload():
        result, error = process_upload(request.files.get("file"))
        if error:
            message, status = error
            return jsonify({"error": message}), status
        return jsonify({"message": "CSV processed.", **result}), 200

    @app.post("/api/screen")
    @roles_required("ADMINISTRATOR", "ANALYST")
    def api_screen():
        conn = database()
        try:
            count = screen_pending(conn)
            return jsonify({"message": "Screening completed.", "screened": count}), 200
        except Exception as exc:
            conn.rollback()
            app.logger.error("api_screening_failed", extra={"error_type": type(exc).__name__})
            return jsonify({"error": "Screening could not be completed."}), 500
        finally:
            conn.close()

    @app.get("/api/report")
    @roles_required("ADMINISTRATOR", "ANALYST", "AUDITOR")
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
            page = query_integer("page", 1, 1, 2147483647)
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
        except Exception as exc:
            app.logger.error("api_report_failed", extra={"error_type": type(exc).__name__})
            return jsonify({"error": "Report could not be generated."}), 500
        finally:
            conn.close()

    @app.post("/api/audit/verify")
    @roles_required("ADMINISTRATOR")
    def api_audit_verify():
        conn = database()
        try:
            ok, message = verify_chain(conn)
            with conn:
                log_event(conn, "AUDIT_VERIFY", "result=" + ("ok" if ok else "failed"))
            return jsonify({"valid": ok, "message": message}), (200 if ok else 409)
        except Exception as exc:
            conn.rollback()
            app.logger.error("api_audit_verification_failed", extra={"error_type": type(exc).__name__})
            return jsonify({"error": "Audit verification could not be completed."}), 500
        finally:
            conn.close()

    @app.get("/")
    @roles_required("ADMINISTRATOR", "ANALYST", "AUDITOR")
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
    @roles_required("ADMINISTRATOR")
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
    @roles_required("ADMINISTRATOR", "ANALYST")
    def screen():
        conn = database()
        try:
            count = screen_pending(conn)
            flash(f"Screening completed. {count} pending transaction(s) processed.", "success")
        except Exception as exc:
            conn.rollback()
            app.logger.error("screening_action_failed", extra={"error_type": type(exc).__name__})
            flash("Screening could not be completed. Please try again.", "error")
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    @app.post("/audit/verify")
    @roles_required("ADMINISTRATOR")
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
        except Exception as exc:
            conn.rollback()
            app.logger.error("audit_verification_failed", extra={"error_type": type(exc).__name__})
            flash("Audit verification could not be completed.", "error")
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
