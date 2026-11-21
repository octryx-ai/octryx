"""Contract: the real connection tests against local stubs that require Bearer or Basic.

Each stub is a real loopback HTTP server reached through the pinned egress transport (the
loopback stub exemption decides, nothing is bypassed). One stub accepts only
``Bearer <PAT>``, the other only ``Basic <user>:<password>``. Every config carries *both* secrets,
so a cross-fallback would be visible: the stub records each ``Authorization`` header it sees.
A matching mode connects; the other mode is answered 401 and the result carries the fixed,
mode-aware hint, never a secret or the response body.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json

import httpx
import pytest

from app.services.connector_test import collab
from tests.egress_support import stub_settings, use_stub_settings

# Imported under neutral names, so pytest does not collect the probes themselves as tests.
probe_confluence = collab.test_confluence_connection
probe_jira = collab.test_jira_connection
PROBES = {"confluence": probe_confluence, "jira": probe_jira}
PAT = "stub-personal-access-token"
USER, PASSWORD = "svc-user", "stub-password"
BASIC = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()


@contextlib.asynccontextmanager
async def _stub(accepted: str):
    """A loopback server answering 200 only for the exact ``accepted`` Authorization header."""
    seen: list[str] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        authorization = next(
            (line.split(":", 1)[1].strip() for line in head.split("\r\n") if line.lower().startswith("authorization:")),
            "",
        )
        seen.append(authorization)
        ok = authorization == accepted
        body = json.dumps({"size": 1, "name": "svc"} if ok else {"message": f"rejected {PASSWORD}"}).encode()
        status = b"200 OK" if ok else b"401 Unauthorized"
        writer.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\nConnection: close\r\n"
                     + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", seen
    finally:
        server.close()
        await server.wait_closed()


def _confluence(url: str, mode: str | None) -> dict:
    config = {"confluence_url": url, "confluence_username": USER, "confluence_password": PASSWORD,
              "confluence_token": PAT}
    return {**config, "confluence_auth_mode": mode} if mode else config


def _jira(url: str, mode: str | None) -> dict:
    config = {"jira_url": url, "jira_username": USER, "jira_password": PASSWORD, "jira_token": PAT,
              "jira_email": "svc@example.test"}
    return {**config, "jira_auth_mode": mode} if mode else config


def _no_secret_in(result: dict) -> None:
    text = json.dumps(result)
    assert PAT not in text and PASSWORD not in text and "rejected" not in text


@pytest.mark.parametrize(("probe", "config"), [("confluence", _confluence), ("jira", _jira)])
async def test_a_bearer_only_server_accepts_pat_mode_and_refuses_basic_with_a_hint(monkeypatch, probe, config):
    probe = PROBES[probe]
    async with _stub(f"Bearer {PAT}") as (url, seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=url.removeprefix("http://")))
        ok = await probe(config(url, "bearer_pat"), httpx_module=httpx)
        assert ok["ok"] is True, ok
        assert seen == [f"Bearer {PAT}"], "only the PAT, only as Bearer"

        seen.clear()
        refused = await probe(config(url, "basic"), httpx_module=httpx)
        assert (refused["ok"], refused["http_status"]) == (False, 401)
        assert seen == [BASIC], "basic mode sends the password as Basic, never the token"
        assert "basic authentication disabled" in refused["summary"]
        _no_secret_in(refused)


@pytest.mark.parametrize(("probe", "config"), [("confluence", _confluence), ("jira", _jira)])
async def test_a_basic_only_server_accepts_basic_mode_and_refuses_pat_with_a_hint(monkeypatch, probe, config):
    probe = PROBES[probe]
    async with _stub(BASIC) as (url, seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=url.removeprefix("http://")))
        ok = await probe(config(url, "basic"), httpx_module=httpx)
        assert ok["ok"] is True, ok
        assert seen == [BASIC]

        seen.clear()
        refused = await probe(config(url, "bearer_pat"), httpx_module=httpx)
        assert (refused["ok"], refused["http_status"]) == (False, 401)
        assert seen == [f"Bearer {PAT}"], "PAT mode never falls back to the password"
        assert "Personal access token mode" in refused["summary"]
        _no_secret_in(refused)


async def test_credentials_without_a_mode_never_reach_the_network(monkeypatch):
    async with _stub(BASIC) as (url, seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=url.removeprefix("http://")))
        confluence = await probe_confluence(_confluence(url, None), httpx_module=httpx)
        jira = await probe_jira(_jira(url, None), httpx_module=httpx)
        assert confluence["ok"] is False and "confluence_auth_mode" in confluence["summary"]
        assert jira["ok"] is False and "jira_auth_mode" in jira["summary"]
        assert seen == []
        _no_secret_in(confluence)
        _no_secret_in(jira)


async def test_unknown_or_incomplete_modes_and_bare_cloud_urls_never_reach_the_network(monkeypatch):
    async with _stub(BASIC) as (url, seen):
        use_stub_settings(monkeypatch, stub_settings(hosts=url.removeprefix("http://")))
        unknown = await probe_jira({**_jira(url, None), "jira_auth_mode": "oauth"}, httpx_module=httpx)
        incomplete = await probe_confluence(
            {"confluence_url": url, "confluence_auth_mode": "bearer_pat", "confluence_password": PASSWORD},
            httpx_module=httpx,
        )
        assert unknown["ok"] is False and "jira_auth_mode must be one of" in unknown["summary"]
        assert incomplete["ok"] is False and "personal access token" in incomplete["summary"]
        assert seen == []
    cloud = await probe_confluence(
        {"confluence_url": "https://your-site.atlassian.net", "confluence_auth_mode": "cloud_api_token",
         "confluence_username": "me@example.test", "confluence_token": PAT},
        httpx_module=httpx,
    )
    assert cloud["ok"] is False and "/wiki" in cloud["summary"]
    _no_secret_in(cloud)
