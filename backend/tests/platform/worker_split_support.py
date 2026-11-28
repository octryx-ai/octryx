"""Shared fake database for the worker split tests."""

from __future__ import annotations


class _FakeDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        return None

    async def commit(self) -> None:
        return None
