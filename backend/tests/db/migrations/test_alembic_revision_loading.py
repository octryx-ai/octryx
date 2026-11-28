"""``alembic upgrade head`` from the CLI builds a fresh database the way the runners do."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect

from tests.alembic_model_parity_support import BACKEND_DIR, ScratchDatabase, alembic_version, head_revision


def _environment_without_python_path(**overrides: str) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "DATABASE_URL")}
    return {**environment, **overrides}


def test_alembic_cli_upgrades_a_fresh_database_to_head_like_the_runtime_runners(tmp_path: Path) -> None:
    database = tmp_path / "cli.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=_environment_without_python_path(DATABASE_URL=f"sqlite+aiosqlite:///{database}"),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    migrated = ScratchDatabase("sqlite", f"sqlite+aiosqlite:///{database}")
    tables = migrated.run(lambda connection: set(inspect(connection).get_table_names()))
    assert migrated.run(alembic_version) == head_revision()
    assert {"turn_traces", "mash_platforms", "worker_shifts", "user_invitations"} <= tables
