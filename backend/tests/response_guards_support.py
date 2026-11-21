"""No-op persistence, trace and message callbacks and a dummy database shared by the response guard tests."""

from __future__ import annotations


async def _noop_persist(**kwargs):  # type: ignore[no-untyped-def]
    return None


async def _noop_trace(**kwargs):  # type: ignore[no-untyped-def]
    return None


async def _noop_message(**kwargs):  # type: ignore[no-untyped-def]
    return None


class _DummyDB:
    async def commit(self):  # type: ignore[no-untyped-def]
        return None
