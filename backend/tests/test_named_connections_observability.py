"""Named Grafana, Loki and Prometheus connections: one per instance.

- a call names its ``instance`` (or ``connection``) and runs on exactly that instance's URL (and Grafana
  token); real ``query_loki`` against a fake Loki: the request goes to the named instance only;
- an unknown instance and a call without an instance (several candidates) are refused, the latter with the
  candidates; the default runs only when named explicitly;
- a named Grafana without its token is refused before the call;
- the admin API needs each connector's URL (and Grafana's token); none of them has a connection test.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException

import app.tools.loki as loki_module
from app.services.admin.project.named_connection_service import save_named
from app.services.named_connections.descriptors import DESCRIPTORS
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.tool_config import upsert_tool_config
from app.tools.context import ToolContext
from app.tools.loki import QueryLoki
from tests.knowledge_evidence_seed_support import seed_workspace


def _context(base: dict, *named: ResolvedNamedConnection) -> ToolContext:
    config = {**base, NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named))}
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class Recorder:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    async def __call__(self, params, context):
        self.configs.append(context.project_config)
        return {"ok": True}


async def test_a_loki_query_goes_to_the_named_instance_only(monkeypatch) -> None:
    hosts: list[str] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json={"data": {"result": [{"stream": {}, "values": [["1", "line"]]}]}})

    monkeypatch.setattr(loki_module.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    named = ResolvedNamedConnection("id-eu", "loki", "loki-eu", "workspace", frozenset({"prod-eu"}),
                                    {"loki_url": "https://loki.eu.example.test"})
    context = _context({"loki_url": "https://loki.default.example.test"}, named)
    result = await routed_execute("query_loki", {"query": '{app="x"}', "instance": "PROD-EU"}, context,
                                  QueryLoki().execute)
    assert result["total_lines"] == 1 and hosts == ["loki.eu.example.test"]
    await routed_execute("query_loki", {"query": '{app="x"}', "connection": "default"}, context, QueryLoki().execute)
    assert hosts == ["loki.eu.example.test", "loki.default.example.test"]


@pytest.mark.parametrize("tool, connector, url_field", [
    ("query_prometheus", "prometheus", "prometheus_url"),
    ("list_grafana_alerts", "grafana", "grafana_url"),
])
async def test_without_an_instance_or_with_an_unknown_one_nothing_runs(tool, connector, url_field) -> None:
    named = ResolvedNamedConnection("id-eu", connector, "eu", "workspace", frozenset({"prod-eu"}),
                                    {url_field: "https://eu.example.test", "grafana_token": "fake-token"})
    execute = Recorder()
    context = _context({url_field: "https://default.example.test"}, named)
    ambiguous = await routed_execute(tool, {"query": "up"}, context, execute)
    assert ambiguous["code"] == "connection_ambiguous" and "instance" in ambiguous["error"]
    assert [c["id"] for c in ambiguous["candidates"]] == ["id-eu", "default"]
    unknown = await routed_execute(tool, {"query": "up", "instance": "us"}, context, execute)
    assert unknown["code"] == "connection_not_configured_for_scope" and execute.configs == []
    await routed_execute(tool, {"query": "up", "instance": "prod-eu"}, context, execute)
    assert execute.configs[0][url_field] == "https://eu.example.test"


async def test_a_named_grafana_without_its_token_is_refused() -> None:
    named = ResolvedNamedConnection("id-eu", "grafana", "eu", "workspace", frozenset({"prod-eu"}),
                                    {"grafana_url": "https://eu.example.test"})
    execute = Recorder()
    refused = await routed_execute("list_grafana_alerts", {"instance": "prod-eu"},
                                   _context({"grafana_url": "https://default.example.test", "grafana_token": "d"},
                                            named), execute)
    assert refused["code"] == "named_connection_credential_unavailable" and execute.configs == []


async def test_the_admin_api_needs_the_url_and_grafanas_token(db) -> None:
    workspace_id = await seed_workspace(db)
    for tool, url in (("grafana", "grafana_url"), ("loki", "loki_url"), ("prometheus", "prometheus_url")):
        await upsert_tool_config(db, tool_name=tool, project_id=workspace_id, config={url: "https://d.test"},
                                 is_active=True)
        with pytest.raises(HTTPException) as refused:
            await save_named(db, connector=tool, project_id=workspace_id, actor_id=None,
                             payload={"name": "eu", "bound_scopes": ["prod-eu"]})
        assert refused.value.status_code == 422
        assert DESCRIPTORS[tool].testable is False
    with pytest.raises(HTTPException):
        await save_named(db, connector="grafana", project_id=workspace_id, actor_id=None,
                         payload={"name": "eu", "bound_scopes": ["prod-eu"], "grafana_url": "https://g.test"})
    saved = await save_named(db, connector="grafana", project_id=workspace_id, actor_id=None, payload={
        "name": "eu", "bound_scopes": ["Prod-EU"], "grafana_url": "https://g.test", "grafana_token": "fake-1"})
    assert saved["bound_scopes"] == ["prod-eu"] and saved["secret_status"] == {"grafana_token": True}
    loki = await save_named(db, connector="loki", project_id=workspace_id, actor_id=None,
                            payload={"name": "eu", "bound_scopes": ["prod-eu"], "loki_url": "https://l.test"})
    assert loki["fields"] == {"loki_url": "https://l.test"} and loki["secret_status"] == {}
