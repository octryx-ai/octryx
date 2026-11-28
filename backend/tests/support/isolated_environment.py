"""Process environment of the test suite, set before any app module is imported (tests/conftest.py imports it first)."""

from __future__ import annotations

import os
import secrets
import tempfile
import uuid
from pathlib import Path

_RUN_ID = uuid.uuid4().hex[:8]

# File-based SQLite (avoids StaticPool + drop_all table-missing issues); one file per pytest process, never reused.
TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"test_{_RUN_ID}.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DATABASE_PATH}?timeout=120"
AUDIT_FALLBACK_PATH = Path(tempfile.gettempdir()) / f"test_{_RUN_ID}_audit-fallback.jsonl"
APP_DATABASE_PATH = Path(tempfile.gettempdir()) / f"test_{_RUN_ID}_app.db"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{APP_DATABASE_PATH}"
os.environ.setdefault("OCTRYX_AUTH_BCRYPT_ROUNDS", "4")
# The app refuses insecure defaults at start; these test-only values let `pytest backend/tests` run on a fresh clone.
os.environ.setdefault("JWT_SECRET", secrets.token_hex(32))
os.environ.setdefault("ENCRYPTION_KEY", secrets.token_hex(16))
os.environ.setdefault("FORCE_SECURE_AUTH_COOKIES", "true")


def sqlite_files(path: Path) -> list[Path]:
    return [Path(f"{path}{suffix}") for suffix in ("", "-wal", "-shm", "-journal", ".init.lock")]


__all__ = ["APP_DATABASE_PATH", "AUDIT_FALLBACK_PATH", "TEST_DATABASE_PATH", "TEST_DATABASE_URL", "sqlite_files"]
