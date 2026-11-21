"""Alembic environment configuration with async support."""

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.migration_metadata import load_migration_metadata

config = context.config

if config.config_file_name is not None:
    # Keep loggers that already exist: a migration run inside a live process (the test suite,
    # any in-process runner) must not silence the application's own loggers for the rest of
    # that process. The Alembic CLI starts fresh, so its output is unchanged.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Every model whose table the migrations own, including the MASH master models.
target_metadata = load_migration_metadata()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI_DIR = Path(config.config_file_name).resolve().parent if config.config_file_name else _REPO_ROOT


def _normalize_sqlite_url(url: str, *, base_dir: Path) -> str:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if not url.startswith(prefix):
            continue
        raw_path = url[len(prefix) :].strip()
        if not raw_path or raw_path == ":memory:":
            return url
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return f"{prefix}{path}"
        return f"{prefix}{(base_dir / path).resolve()}"
    return url


def _configured_database_url() -> str:
    # A programmatic caller (a migration test on its own scratch database) names its URL explicitly; that wins over
    # an inherited process DATABASE_URL, which would otherwise migrate the wrong database.
    explicit_url = config.attributes.get("database_url")
    if explicit_url:
        return _normalize_sqlite_url(explicit_url, base_dir=_REPO_ROOT)
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return _normalize_sqlite_url(env_url, base_dir=_REPO_ROOT)
    return _normalize_sqlite_url(config.get_main_option("sqlalchemy.url"), base_dir=_ALEMBIC_INI_DIR)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode – generates SQL script."""
    url = _configured_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' async mode."""
    database_url = _configured_database_url()
    config.set_main_option("sqlalchemy.url", database_url)
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
