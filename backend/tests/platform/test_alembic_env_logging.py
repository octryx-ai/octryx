"""An in-process Alembic run keeps the application's loggers working (``fileConfig`` would otherwise disable every
existing logger for the rest of the worker)."""

from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_an_in_process_alembic_run_leaves_existing_loggers_enabled(tmp_path: Path, monkeypatch) -> None:
    probe = logging.getLogger("app.services.alembic_env_logging_probe")
    assert probe.disabled is False

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'env-logging.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    # env.py calls asyncio.run, so it runs outside pytest-asyncio's loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(command.current, config).result()

    assert probe.disabled is False
