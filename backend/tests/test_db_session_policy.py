from __future__ import annotations

import pytest

from app.db import core as db_core
from app.services.request_context import reset_current_rls_user_id, set_current_rls_user_id


class _FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def execute(self, *_args, **_kwargs) -> None:
        self.events.append("execute")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def close(self) -> None:
        self.events.append("close")


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        self.session.events.append("enter")
        return self.session

    async def __aexit__(self, _exc_type, _exc, _tb) -> bool:
        self.session.events.append("exit")
        return False


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self.session)


@pytest.mark.asyncio
async def test_get_db_commits_successful_request_unit(monkeypatch):
    events: list[str] = []
    session = _FakeSession(events)
    monkeypatch.setattr(db_core, "async_session_factory", _FakeSessionFactory(session))
    monkeypatch.setattr(db_core, "_is_sqlite", True)

    generator = db_core.get_db()
    yielded_session = await anext(generator)

    assert yielded_session is session
    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert events == ["enter", "commit", "close", "exit"]


@pytest.mark.asyncio
async def test_get_db_rolls_back_failed_request_unit(monkeypatch):
    events: list[str] = []
    session = _FakeSession(events)
    monkeypatch.setattr(db_core, "async_session_factory", _FakeSessionFactory(session))
    monkeypatch.setattr(db_core, "_is_sqlite", True)

    generator = db_core.get_db()
    yielded_session = await anext(generator)

    assert yielded_session is session
    with pytest.raises(RuntimeError, match="boom"):
        await generator.athrow(RuntimeError("boom"))

    assert events == ["enter", "rollback", "close", "exit"]


@pytest.mark.asyncio
async def test_get_db_fails_closed_when_postgres_rls_context_cannot_be_set(monkeypatch):
    events: list[str] = []

    class FailingRlsSession(_FakeSession):
        async def execute(self, *_args, **_kwargs) -> None:
            self.events.append("execute")
            raise RuntimeError("set_config failed")

    session = FailingRlsSession(events)
    token = set_current_rls_user_id("user-rls")
    monkeypatch.setattr(db_core, "async_session_factory", _FakeSessionFactory(session))
    monkeypatch.setattr(db_core, "_is_sqlite", False)

    try:
        generator = db_core.get_db()
        with pytest.raises(RuntimeError, match="Failed to establish request data isolation"):
            await anext(generator)
    finally:
        reset_current_rls_user_id(token)

    assert events == ["enter", "execute", "rollback", "close", "exit"]
