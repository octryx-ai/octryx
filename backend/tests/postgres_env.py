"""The disposable PostgreSQL servers tests may use, named in the environment as ``OCTRYX_TEST_<NAME>``.

Without the variable the PostgreSQL tests skip; set it to a throwaway server's URL to run them, e.g.
``OCTRYX_TEST_POSTGRES_URL=postgresql+asyncpg://user:password@localhost:5432/octryx_test``.
"""

from __future__ import annotations

import os


def postgres_url(name: str = "POSTGRES_URL") -> str:
    """``postgresql+asyncpg://...`` of the server ``name`` names (``POSTGRES_URL``, ``LEDGER_POSTGRES_URL``), or ''."""
    return os.environ.get(f"OCTRYX_TEST_{name}") or ""


__all__ = ["postgres_url"]
