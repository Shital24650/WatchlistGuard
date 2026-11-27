"""Alembic environment using WATCHLISTGUARD_DATABASE_URL."""
import os
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
url = os.environ.get("WATCHLISTGUARD_DATABASE_URL")
if url:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
