"""The disposable PostgreSQL servers tests may use, named in the environment as ``OCTRYX_TEST_<NAME>``
(e.g. ``OCTRYX_TEST_POSTGRES_URL``); without the variable the PostgreSQL tests skip."""

from __future__ import annotations

import os


def postgres_url(name: str = "POSTGRES_URL") -> str:
    return os.environ.get(f"OCTRYX_TEST_{name}") or ""


__all__ = ["postgres_url"]
