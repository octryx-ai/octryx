"""Shared helpers for the test_codex_seat_device_* modules."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from tests.model_gateway.codex_seat_support import STREAM, UPSTREAM_HEADERS, _body, _headers

ADMIT = "/api/v1/model-gateway/openai/seat/admit"


REPORT = "/api/v1/model-gateway/openai/seat/report"


# What the launcher's seat proxy sends the platform: never the ChatGPT Authorization or account id.
_NOT_TO_THE_PLATFORM = {"authorization", "chatgpt-account-id", "cookie", "x-api-key", "x-codex-turn-metadata"}


def _device(gateway: dict[str, str], credential: str) -> dict[str, str]:
    return {name: value for name, value in _headers(gateway, credential).items() if name not in _NOT_TO_THE_PLATFORM}


async def _admit(client, gateway, credential, body: dict[str, Any] | None = None) -> httpx.Response:
    return await client.post(ADMIT, json=body or _body(), headers=_device(gateway, credential))


async def _report(client, gateway, credential, admitted: dict[str, Any], *, stream: str = STREAM,
                  status: int = 200, headers: dict[str, str] | None = None, **extra: Any) -> httpx.Response:
    payload = {"ticket": admitted["ticket"], "body": admitted["body"], "status_code": status,
               "headers": UPSTREAM_HEADERS if headers is None else headers, "complete": True, "duration_ms": 900,
               "response_b64": base64.b64encode(stream.encode()).decode(), "truncated": False, **extra}
    return await client.post(REPORT, json=payload, headers=_device(gateway, credential))
