"""Named Kubernetes connections: several clusters per Workspace, each an API URL and token.

- a call names its ``cluster`` (or its ``connection``): it runs on exactly that cluster's API with that token,
  never with the default's kubeconfig, context or namespace (real chat tool against a fake API);
- the default serves the cluster of its own ``k8s_context``; an unknown cluster and a call without a cluster
  (several candidates) are refused, the latter listing the candidates;
- a named connection without its token is refused before the call (no fallback to the pod's service account);
  its allowed namespaces bound every call; ``run_kubectl`` never runs on it;
- the admin API needs the API URL and token, keeps the token write-only and the namespaces as a list;
- over the Knowledge MCP the Workspace-credential rule applies per connection: a named API connection is
  served, the default's kubeconfig still is not.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from app.models import BuiltInToolConfig
from app.services.admin.project.named_connection_service import save_named
from app.services.admin.project.named_connection_view import list_named
from app.services.mcp_connector_tools import CONNECTOR_MCP_TOOLS, KUBERNETES_CREDENTIALS_REQUIRED
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, McpCaller, run_governed_mcp_tool
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.tool_config import upsert_tool_config
from app.tools import kubernetes
from app.tools.context import ToolContext
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

PROD_TOKEN, DEFAULT_TOKEN = "fake-prod-token-1", "fake-default-token-2"
DEFAULT = {"kubeconfig_path": "/home/x/.kube/config", "k8s_context": "nonprod", "k8s_namespace": "shop",
           "k8s_use_kubectl": True}


def _prod(**extra) -> ResolvedNamedConnection:
    config = {"k8s_api_url": "https://prod.k8s.example.test", "k8s_token": PROD_TOKEN, **extra}
    return ResolvedNamedConnection("id-prod", "kubernetes", "prod", "workspace", frozenset({"prod"}), config)


def _context(*named: ResolvedNamedConnection, base: dict | None = None) -> ToolContext:
    config = {**(DEFAULT if base is None else base), NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named))}
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class Recorder:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    async def __call__(self, params, context):
        self.configs.append(context.project_config)
        return {"ok": True}


@pytest.fixture
def api(monkeypatch):
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.url.path, request.headers.get("authorization", "")))
        return httpx.Response(200, json={"items": [{"metadata": {"name": "scoring-0", "namespace": "shop"},
                                                    "status": {"phase": "Running"}, "spec": {"containers": []}}]})

    monkeypatch.setattr(kubernetes, "_k8s_transport", lambda verify: httpx.MockTransport(handler))
    monkeypatch.setattr(kubernetes, "_SA_TOKEN_PATH", kubernetes.Path("/nonexistent/sa-token"))
    return seen


async def test_a_cluster_runs_on_its_own_api_and_token_never_the_default_kubeconfig(api) -> None:
    result = await routed_execute("list_k8s_pods", {"namespace": "shop", "cluster": "prod"},
                                  _context(_prod()), kubernetes.ListPods().execute)
    assert result["pods"][0]["name"] == "scoring-0"
    assert api == [("prod.k8s.example.test", "/api/v1/namespaces/shop/pods", f"Bearer {PROD_TOKEN}")]

    execute = Recorder()
    await routed_execute("list_k8s_pods", {"namespace": "shop", "cluster": "prod"}, _context(_prod()), execute)
    config = execute.configs[0]
    for inherited in ("kubeconfig_path", "k8s_context", "k8s_use_kubectl", "k8s_namespace"):
        assert inherited not in config, inherited


async def test_the_default_serves_its_own_context_and_everything_else_is_refused() -> None:
    execute = Recorder()
    await routed_execute("list_k8s_pods", {"namespace": "shop", "cluster": "nonprod"}, _context(_prod()), execute)
    assert execute.configs[0]["kubeconfig_path"] == DEFAULT["kubeconfig_path"]
    await routed_execute("list_k8s_pods", {"namespace": "shop", "connection": "default"}, _context(_prod()), execute)
    assert len(execute.configs) == 2

    unknown = await routed_execute("list_k8s_pods", {"namespace": "shop", "cluster": "elsewhere"},
                                   _context(_prod()), execute)
    assert unknown["code"] == "connection_not_configured_for_scope"
    ambiguous = await routed_execute("list_k8s_namespaces", {}, _context(_prod()), execute)
    assert ambiguous["code"] == "connection_ambiguous"
    assert [c["id"] for c in ambiguous["candidates"]] == ["id-prod", "default"]
    assert "cluster" in ambiguous["error"] and len(execute.configs) == 2


async def test_without_its_token_a_named_cluster_is_refused_never_the_service_account() -> None:
    execute = Recorder()
    tokenless = ResolvedNamedConnection("id-prod", "kubernetes", "prod", "workspace", frozenset({"prod"}),
                                        {"k8s_api_url": "https://prod.k8s.example.test"})
    refused = await routed_execute("list_k8s_pods", {"namespace": "shop", "cluster": "prod"},
                                   _context(tokenless), execute)
    assert refused["code"] == "named_connection_credential_unavailable" and execute.configs == []


@pytest.mark.parametrize("params, code", [
    ({"namespace": "shop"}, None),
    ({"namespace": "payments"}, "named_connection_request_not_allowed"),
    ({}, "named_connection_request_not_allowed"),
    ({"namespace": "shop", "all_namespaces": True}, "named_connection_request_not_allowed"),
])
async def test_allowed_namespaces_bound_every_call_on_the_connection(params, code) -> None:
    execute = Recorder()
    result = await routed_execute("kubernetes_topology_snapshot", {**params, "cluster": "prod"},
                                  _context(_prod(k8s_allowed_namespaces=["shop", "demo-jobs"])), execute)
    if code is None:
        assert result == {"ok": True}
    else:
        assert result["code"] == code and execute.configs == []


async def test_run_kubectl_never_runs_on_a_named_connection() -> None:
    execute = Recorder()
    refused = await routed_execute("run_kubectl", {"args": "get pods", "connection": "prod"},
                                   _context(_prod()), execute)
    assert refused["code"] == "named_connection_request_not_allowed" and execute.configs == []
    await routed_execute("run_kubectl", {"args": "get pods", "connection": "default"}, _context(_prod()), execute)
    assert execute.configs[0]["kubeconfig_path"] == DEFAULT["kubeconfig_path"]


async def _k8s_workspace(db, default: dict) -> str:
    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="kubernetes", project_id=workspace_id, is_active=True, config=default))
    await db.flush()
    return workspace_id


async def test_the_admin_api_needs_url_and_token_and_keeps_the_token_write_only(db) -> None:
    workspace_id = await _k8s_workspace(db, dict(DEFAULT))
    body = {"name": "prod", "bound_scopes": ["prod"], "k8s_api_url": "https://prod.k8s.example.test"}
    with pytest.raises(HTTPException) as refused:
        await save_named(db, connector="kubernetes", project_id=workspace_id, payload=body, actor_id=None)
    assert refused.value.status_code == 422 and "k8s_token" in refused.value.detail["message"]

    saved = await save_named(db, connector="kubernetes", project_id=workspace_id, actor_id=None, payload={
        **body, "k8s_token": PROD_TOKEN, "k8s_allowed_namespaces": "shop, demo-jobs", "k8s_verify_tls": "false"})
    assert saved["fields"]["k8s_allowed_namespaces"] == ["shop", "demo-jobs"]
    assert saved["fields"]["k8s_verify_tls"] is False
    assert saved["secret_status"] == {"k8s_token": True}
    listed = await list_named(db, connector="kubernetes", project_id=workspace_id)
    assert listed["descriptor"]["binding"]["label"] == "cluster"
    assert PROD_TOKEN not in json.dumps(listed) and "_secret_ref" not in json.dumps(listed)
    with pytest.raises(HTTPException) as bad_key:
        await save_named(db, connector="kubernetes", project_id=workspace_id, actor_id=None,
                         payload={**body, "name": "x", "bound_scopes": ["-bad"], "k8s_token": "t"})
    assert bad_key.value.detail["code"] == "named_connection_scopes_invalid"


@pytest.fixture
def governed(monkeypatch):
    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)


async def test_over_mcp_the_credential_rule_holds_per_connection(db, api, governed) -> None:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await upsert_tool_config(db, tool_name="kubernetes", project_id=workspace_id, config=dict(DEFAULT), is_active=True)
    await save_named(db, connector="kubernetes", project_id=workspace_id, actor_id=None, payload={
        "name": "prod", "bound_scopes": ["prod"], "k8s_api_url": "https://prod.k8s.example.test",
        "k8s_token": PROD_TOKEN})
    await db.commit()
    caller = McpCaller(user_id=member_id, grant_id="grant-1", scopes=("knowledge:read", "knowledge:write"),
                       workspace_header=workspace_id, client_name="claude-code")
    assert "list_k8s_pods" in CONNECTOR_MCP_TOOLS

    served = await run_governed_mcp_tool(db, caller=caller, tool_name="list_k8s_pods",
                                         arguments={"namespace": "shop", "cluster": "prod"})
    assert served["pods"][0]["name"] == "scoring-0"
    assert api == [("prod.k8s.example.test", "/api/v1/namespaces/shop/pods", f"Bearer {PROD_TOKEN}")]

    kubeconfig = await run_governed_mcp_tool(db, caller=caller, tool_name="list_k8s_pods",
                                             arguments={"namespace": "shop", "connection": "default"})
    assert {key: kubeconfig[key] for key in KUBERNETES_CREDENTIALS_REQUIRED} == KUBERNETES_CREDENTIALS_REQUIRED
    assert len(api) == 1


async def test_a_connection_test_never_falls_back_to_the_service_account(db, monkeypatch) -> None:
    import app.services.admin.project.named_connection_service as service
    from app.services.admin.project.named_connection_service import test_named as run_named_test

    workspace_id = await _k8s_workspace(db, dict(DEFAULT))
    saved = await save_named(db, connector="kubernetes", project_id=workspace_id, actor_id=None, payload={
        "name": "prod", "bound_scopes": ["prod"], "k8s_api_url": "https://prod.k8s.example.test",
        "k8s_token": PROD_TOKEN})

    async def secret_gone(db, connection):  # the stored token no longer resolves
        return {"k8s_api_url": "https://prod.k8s.example.test"}

    async def never(tool, config):
        raise AssertionError("no test runs without the connection's own token")

    monkeypatch.setattr(service, "resolved_config", secret_gone)
    with pytest.raises(HTTPException) as refused:
        await run_named_test(db, connector="kubernetes", project_id=workspace_id, connection_id=saved["id"],
                             payload={}, run_connection_test=never, actor_id=None)
    assert refused.value.status_code == 422
