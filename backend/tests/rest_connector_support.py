"""Shared by the custom REST connector tests: one API answering through the real pinned ``custom_rest`` egress."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.services.outbound_egress import CONNECTION_CUSTOM_REST, PinnedEgressTransport
from app.services.rest_connector import auth as rest_auth

API = "https://api.example.test/v1"
SECRET = "tok-SE" + "CRET-4711"


def recorded_api(monkeypatch) -> SimpleNamespace:
    """Answers through the real ``custom_rest`` pinned transport; ``api.answer(request)`` decides the response."""
    recorder = SimpleNamespace(requests=[], answer=lambda request: httpx.Response(200, json={"items": []}))

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.requests.append(request)
        return recorder.answer(request)

    def client(timeout: float) -> httpx.AsyncClient:
        transport = PinnedEgressTransport(CONNECTION_CUSTOM_REST, inner=httpx.MockTransport(handler))
        return httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport)

    async def no_sleep(seconds: float) -> None:
        recorder.slept = seconds

    monkeypatch.setattr("app.services.rest_connector.executor.rest_client", client)
    monkeypatch.setattr("app.services.rest_connector.http_call._sleep", no_sleep)
    rest_auth._TOKEN_CACHE.clear()
    return recorder


__all__ = ["API", "SECRET", "recorded_api"]
