"""Authentication, password hashing, and server-side role enforcement."""
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = {"ADMINISTRATOR", "ANALYST", "AUDITOR"}
_DUMMY_PASSWORD_HASH = generate_password_hash("unusable-dummy-password-for-timing-only", method="scrypt")


def create_user(conn, username, password, role):
    if not isinstance(username, str) or not isinstance(password, str) or not isinstance(role, str):
        raise ValueError("Username, password, and role must be strings.")
    username = (username or "").strip()
    role = (role or "").upper()
    if len(username) < 3 or len(username) > 80 or not username.isprintable():
        raise ValueError("Username must be 3 to 80 printable characters.")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must be at least 12 characters and at most 1024 characters.")
    if role not in ROLES:
        raise ValueError("Role must be ADMINISTRATOR, ANALYST, or AUDITOR.")
    password_hash = generate_password_hash(password, method="scrypt")
    active = True  # psycopg uses BOOLEAN; SQLite stores this as integer 1.
    conn.execute("INSERT INTO app_users(username,password_hash,role,active) VALUES(?,?,?,?)",
                 (username, password_hash, role, active))
    return conn.execute("SELECT id,username,role,active,created_at FROM app_users WHERE username=?", (username,)).fetchone()


def authenticate(conn, username, password):
    if not isinstance(password, str) or len(password) > 1024:
        return None
    if not isinstance(username, str):
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None
    user = conn.execute("SELECT id,username,password_hash,role,active FROM app_users WHERE username=?",
                        ((username or "").strip(),)).fetchone()
    if not user:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None
    password_matches = check_password_hash(user["password_hash"], password)
    if not user["active"] or not password_matches:
        return None
    return user


def current_user():
    if hasattr(g, "watchlistguard_user"):
        return g.watchlistguard_user
    user_id = session.get("user_id")
    if not user_id:
        g.watchlistguard_user = None
        return None
    from .db import close, connect, initialize
    try:
        conn = connect(current_app.config["DATABASE"])
    except Exception:
        session.clear()
        g.watchlistguard_user = None
        return None
    try:
        try:
            initialize(conn)
            user = conn.execute("SELECT id,username,role,active FROM app_users WHERE id=?", (user_id,)).fetchone()
            g.watchlistguard_user = user if user and user["active"] else None
        except Exception:
            g.watchlistguard_user = None
        if g.watchlistguard_user is None:
            session.clear()
        return g.watchlistguard_user
    finally:
        close(conn)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    allowed = set(roles)
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Authentication required."}), 401
                return redirect(url_for("login", next=request.path))
            if user["role"] not in allowed:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Insufficient permissions."}), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate
