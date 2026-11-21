"""Stubbed connector APIs, the tool runner and the Jira routes shared by the connector evidence coverage tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.tools.registry import TOOL_REGISTRY

JIRA = "https://jira.example.test"
CONFLUENCE = "https://wiki.example.test/confluence"
BITBUCKET = "https://bitbucket.example.test"
SERVICENOW = "https://acme.service-now.com"
SHAREPOINT = "https://acme.sharepoint.com"
SONAR = "https://sonar.example.test"
AZURE = "https://dev.azure.com/acme"
GRAFANA = "https://grafana.example.test"
ARGOCD = "https://argocd.example.test"
SYS_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


# --- stubbed connector APIs ---------------------------------------------------------------------------


class _Response:
    def __init__(self, url: str, payload: Any) -> None:
        self.status_code = 200
        self._payload = payload
        self.headers = {"content-type": "image/png"}
        self.content = b"png"
        self.text = payload if isinstance(payload, str) else ""
        self.request = SimpleNamespace(url=url)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _route(routes: dict[str, Any], url: str) -> Any:
    for fragment, payload in routes.items():
        if fragment in url:
            return payload
    raise AssertionError(f"unexpected request: {url}")


def _client_factory(routes: dict[str, Any]):
    class _Client:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def get(self, url, **_kwargs):
            return _Response(str(url), _route(routes, str(url)))

        async def post(self, url, **_kwargs):
            return _Response(str(url), _route(routes, str(url)))

    return _Client


def _http_json(routes: dict[str, Any]):
    async def fake(method, url, **_kwargs):
        return _route(routes, str(url))

    return fake


def _context(**config) -> SimpleNamespace:
    return SimpleNamespace(
        project_config=config, turn_context_snapshot=None, current_user_message="", project_ids=[], user_id="u1", db=None
    )


def _issue(key: str) -> dict:
    return {"key": key, "fields": {"summary": "Failover drill blocked", "status": {"name": "Open"}}}


async def _run(name: str, params: dict, context: Any) -> dict:
    return await TOOL_REGISTRY[name].execute(params, context)


# Jira


def _jira_get(monkeypatch, routes: dict[str, Any]) -> None:
    async def fake_api(client, jira_url, path, **_kwargs):
        return _route(routes, path), "2"

    async def fake_agile(client, jira_url, path, **_kwargs):
        return _route(routes, path)

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_api)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_agile_get", fake_agile)


JIRA_ROUTES = {
    # First match wins: the more specific path first.
    "/project/search": {"values": [{"key": "OPS", "name": "Operations", "id": "1"}]},
    "/search": {"issues": [_issue("OPS-2")], "total": 1},
    "/comment": {"comments": []},
    "/issue/OPS-2": _issue("OPS-2"),
    "/sprint/": {"issues": [_issue("OPS-2")]},
    "/board": {"values": [{"id": 7, "name": "OPS board", "location": {"projectKey": "OPS"}}]},
    "/versions": [{"id": "10020", "name": "2.4.20"}],
}
