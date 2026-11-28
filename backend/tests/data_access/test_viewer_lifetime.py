from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.middleware.context import DataViewerScopeMiddleware
from app.models import Session
from app.services.data_access import (
    Viewer,
    ViewerNotSetError,
    as_viewer,
    bind_request_viewer,
    current_viewer,
)


async def _call(app) -> None:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await DataViewerScopeMiddleware(app)({"type": "http", "method": "GET", "path": "/", "headers": []}, receive, send)
    assert sent[0]["status"] == 200


def _route_starting(work) -> tuple[object, list[asyncio.Task]]:
    started: list[asyncio.Task] = []

    async def app(_scope, _receive, send) -> None:
        bind_request_viewer("request-user")
        started.append(asyncio.create_task(work()))
        await asyncio.sleep(0)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app, started


async def test_a_task_a_request_leaves_running_reads_as_nobody_after_the_response(db):
    request_done = asyncio.Event()
    seen: list[object] = []

    async def background() -> None:
        seen.append(current_viewer())
        await request_done.wait()
        seen.append(current_viewer())
        await db.execute(select(Session))

    app, started = _route_starting(background)
    await _call(app)
    request_done.set()
    with pytest.raises(ViewerNotSetError):
        await started[0]
    assert seen == [Viewer("request-user"), None]


async def test_a_task_that_declares_its_viewer_keeps_reading_after_the_response(db):
    request_done = asyncio.Event()

    async def background() -> list[str]:
        with as_viewer("request-user"):
            await request_done.wait()
            assert current_viewer() == Viewer("request-user")
            return list((await db.execute(select(Session.id))).scalars())

    app, started = _route_starting(background)
    await _call(app)
    request_done.set()
    assert isinstance(await started[0], list)


async def test_a_request_never_reads_as_the_viewer_of_the_code_that_serves_it():
    seen: list[object] = []

    async def app(_scope, _receive, send) -> None:
        seen.append(current_viewer())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    with as_viewer("server-side"):
        await _call(app)
        assert current_viewer() == Viewer("server-side")
    assert seen == [None]
