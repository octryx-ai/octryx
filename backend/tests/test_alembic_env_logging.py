"""An in-process Alembic run keeps the application's loggers working.

``alembic/env.py`` applies ``alembic.ini``'s logging section with ``fileConfig``. With the default
``disable_existing_loggers=True`` that silenced every logger that already existed, for the rest of
the process: after any in-process migration test, an unrelated test in the same worker could no
longer see an application warning (observed: the knowledge projection worker's recovery warning).
"""

from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[1]


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
