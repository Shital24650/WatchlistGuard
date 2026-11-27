"""Build an escaped PostgreSQL URL from Compose credentials before startup."""
import os
import sys
from urllib.parse import quote


def database_url_from_environment(environment):
    """Return a supplied URL or construct one from separate PostgreSQL fields."""
    configured_url = environment.get("WATCHLISTGUARD_DATABASE_URL")
    if configured_url:
        return configured_url

    keys = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    configured = any(key in environment for key in keys)
    if not configured:
        return None

    missing = [key for key in keys if not environment.get(key)]
    if missing:
        raise RuntimeError("Missing required PostgreSQL settings: " + ", ".join(missing))

    user = quote(environment["POSTGRES_USER"], safe="")
    password = quote(environment["POSTGRES_PASSWORD"], safe="")
    database = quote(environment["POSTGRES_DB"], safe="")
    host = environment.get("POSTGRES_HOST", "postgres")
    port = environment.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def main():
    database_url = database_url_from_environment(os.environ)
    if database_url:
        os.environ["WATCHLISTGUARD_DATABASE_URL"] = database_url

    command = sys.argv[1:] or [
        "gunicorn",
        "--workers", os.environ.get("GUNICORN_WORKERS", "2"),
        "--threads", os.environ.get("GUNICORN_THREADS", "4"),
        "--timeout", os.environ.get("GUNICORN_TIMEOUT", "60"),
        "--graceful-timeout", os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"),
        "--bind", f"0.0.0.0:{os.environ.get('PORT', '5000')}",
        "app:app",
    ]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
