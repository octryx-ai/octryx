"""Named Azure and GCP connections per subscription or project: a call runs with exactly its credential,
unknown or missing ones are refused."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.admin.project.named_connection_service import save_named
from app.services.named_connections.routes_model import (
    NAMED_CONNECTIONS_KEY,
    NamedConnectionRoutes,
    ResolvedNamedConnection,
)
from app.services.named_connections.tool_routing import routed_execute
from app.services.tool_config import upsert_tool_config
from app.tools.connectors import azure as azure_module
from app.tools.connectors import microsoft_graph
from app.tools.context import ToolContext
from tests.knowledge_evidence_seed_support import seed_workspace

SUB_A, SUB_B, SUB_X = ("aaaaaaaa-0000-0000-0000-00000000000a", "bbbbbbbb-0000-0000-0000-00000000000b",
                       "cccccccc-0000-0000-0000-00000000000c")
AZURE_DEFAULT = {"azure_tenant_id": "t-default", "azure_client_id": "c-default", "azure_client_secret": "s-default",
                 "azure_subscription_ids": [SUB_B], "outlook_tenant_id": "t-outlook", "outlook_client_id": "c-outlook",
                 "outlook_client_secret": "s-outlook"}
RIVER = ResolvedNamedConnection("az-risk", "azure", "risk", "workspace", frozenset({SUB_A}), {
    "azure_tenant_id": "t-risk", "azure_client_id": "c-risk", "azure_client_secret": "s-risk"})


def _context(base: dict, *named: ResolvedNamedConnection) -> ToolContext:
    config = {**base, NAMED_CONNECTIONS_KEY: NamedConnectionRoutes(tuple(named))}
    return ToolContext(user_id="u", project_ids=["p"], roles=["admin"], session_id="s", project_config=config)


class Recorder:
    def __init__(self) -> None:
        self.configs: list[dict] = []

    async def __call__(self, params, context):
        self.configs.append(context.project_config)
        return {"ok": True}


async def test_a_real_azure_tool_signs_in_with_the_named_principal_only(monkeypatch) -> None:
    sign_ins: list[str] = []
    calls: list[str] = []

    async def form_json(method, url, form_data=None, **kwargs):
        sign_ins.append(f"{url.split('/')[3]}:{form_data['client_id']}")
        return {"access_token": f"token-{form_data['client_id']}"}

    async def http_json(method, url, headers=None, **kwargs):
        calls.append(f"{url.split('/subscriptions/')[1].split('/')[0]}:{(headers or {}).get('Authorization')}")
        return {"value": [{"name": "vm-1"}]}

    monkeypatch.setattr(microsoft_graph, "_http_form_json", form_json)
    monkeypatch.setattr(azure_module, "_http_json", http_json)
    await routed_execute("list_azure_vms", {"subscription_id": SUB_A}, _context(AZURE_DEFAULT, RIVER),
                         azure_module.ListAzureVirtualMachinesTool().execute)
    assert sign_ins == ["t-risk:c-risk"], "never the Outlook principal of the merged config"
    assert calls == [f"{SUB_A}:Bearer token-c-risk"], "only the connection's own subscription"


@pytest.mark.parametrize("params, client", [
    ({"subscription_id": SUB_A.upper()}, "c-risk"),
    ({"resource_id": f"/subscriptions/{SUB_A}/resourceGroups/rg/providers/x/y"}, "c-risk"),
    ({"subscription_id": SUB_B}, "c-default"),
])
async def test_azure_routes_by_subscription_and_resource(params, client) -> None:
    execute = Recorder()
    await routed_execute("get_azure_monitor_metrics", params, _context(AZURE_DEFAULT, RIVER), execute)
    config = execute.configs[0]
    assert config["azure_client_id"] == client
    if client == "c-risk":
        assert config["azure_subscription_ids"] == [SUB_A]
        assert not any(key.startswith("outlook_") for key in config)


async def test_azure_refuses_unknown_and_unnamed_subscriptions_and_a_missing_secret() -> None:
    execute = Recorder()
    unknown = await routed_execute("start_azure_vm", {"subscription_id": SUB_X}, _context(AZURE_DEFAULT, RIVER), execute)
    assert unknown["code"] == "connection_not_configured_for_scope"
    unnamed = await routed_execute("list_azure_vms", {}, _context(AZURE_DEFAULT, RIVER), execute)
    assert unnamed["code"] == "connection_ambiguous" and "subscription" in unnamed["error"]
    secretless = ResolvedNamedConnection("az-risk", "azure", "risk", "workspace", frozenset({SUB_A}),
                                         {"azure_tenant_id": "t", "azure_client_id": "c"})
    refused = await routed_execute("start_azure_vm", {"subscription_id": SUB_A},
                                   _context(AZURE_DEFAULT, secretless), execute)
    assert refused["code"] == "named_connection_credential_unavailable" and execute.configs == []


GCP_DEFAULT = {"gcp_project_id": "demo-dev-4711", "gcp_access_token": "fake-default"}
PROD = ResolvedNamedConnection("gcp-prod", "gcp", "prod", "workspace", frozenset({"prod-4711"}),
                               {"gcp_access_token": "fake-prod", "gcp_region": "europe-west6"})


async def test_gcp_routes_by_project_and_never_lends_the_default_project() -> None:
    execute = Recorder()
    await routed_execute("list_gcp_compute_instances", {"project_id": "PROD-4711"}, _context(GCP_DEFAULT, PROD),
                         execute)
    assert execute.configs[0]["gcp_access_token"] == "fake-prod" and "gcp_project_id" not in execute.configs[0]
    await routed_execute("list_gcp_compute_instances", {"project_id": "demo-dev-4711"},
                         _context(GCP_DEFAULT, PROD), execute)
    assert execute.configs[1]["gcp_access_token"] == "fake-default"
    await routed_execute("list_gcp_cloud_sql_instances", {"project_id": "prod-4711"},
                         _context(GCP_DEFAULT, PROD), execute)
    assert execute.configs[2]["gcp_access_token"] == "fake-prod", "a Cloud SQL tool is routed like the others"
    other = await routed_execute("list_gcp_gke_clusters", {"project_id": "elsewhere-1"}, _context(GCP_DEFAULT, PROD),
                                 execute)
    assert other["code"] == "connection_not_configured_for_scope"
    tokenless = ResolvedNamedConnection("gcp-prod", "gcp", "prod", "workspace", frozenset({"prod-4711"}), {})
    refused = await routed_execute("list_gcp_gke_clusters", {"project_id": "prod-4711"},
                                   _context(GCP_DEFAULT, tokenless), execute)
    assert refused["code"] == "named_connection_credential_unavailable" and len(execute.configs) == 3


async def test_the_admin_api_needs_azures_principal_and_a_gcp_credential(db) -> None:
    workspace_id = await seed_workspace(db)
    await upsert_tool_config(db, tool_name="azure", project_id=workspace_id, config={"azure_tenant_id": "t"},
                             is_active=True)
    await upsert_tool_config(db, tool_name="gcp", project_id=workspace_id, config={"gcp_project_id": "demo-dev-4711"},
                             is_active=True)
    with pytest.raises(HTTPException):
        await save_named(db, connector="azure", project_id=workspace_id, actor_id=None, payload={
            "name": "risk", "bound_scopes": [SUB_A], "azure_tenant_id": "t", "azure_client_id": "c"})
    with pytest.raises(HTTPException):
        await save_named(db, connector="gcp", project_id=workspace_id, actor_id=None, payload={
            "name": "prod", "bound_scopes": ["prod-4711"], "gcp_region": "europe-west6"})
    azure = await save_named(db, connector="azure", project_id=workspace_id, actor_id=None, payload={
        "name": "risk", "bound_scopes": [SUB_A.upper()], "azure_tenant_id": "t", "azure_client_id": "c",
        "azure_client_secret": "fake-s"})
    assert azure["bound_scopes"] == [SUB_A] and azure["secret_status"] == {"azure_client_secret": True}
    gcp = await save_named(db, connector="gcp", project_id=workspace_id, actor_id=None, payload={
        "name": "prod", "bound_scopes": ["prod-4711"], "gcp_access_token": "fake-t"})
    assert gcp["secret_status"] == {"gcp_service_account_json": False, "gcp_access_token": True}
