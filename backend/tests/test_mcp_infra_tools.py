"""Kubernetes and AWS read tools on the Knowledge MCP.

Through the real runner (``run_governed_mcp_tool``), the chat tool classes and a fake cluster / fake boto, no network:

- the registered set equals the allow list; no write, action, log, config or secret tool is ever served;
- the chat's gates hold: connector policy ``disabled_tools`` (denied), activation (not configured / deactivated),
  ``aws_allowed_services``; a foreign Workspace is ``not_found``;
- Kubernetes needs the Workspace's own API URL and token (never the host kubeconfig or the pod's own token);
- AWS needs the Workspace's own keys or role, or the admin opt-in ``allow_platform_credentials`` (audited);
- every result carries the ``content_is_data`` notice and is otherwise the chat tool's result.
"""

from __future__ import annotations

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from app.models import AuditLog, Project
from app.services.connector_policy.service import upsert_connector_policy
from app.services.mcp_connector_registration import register_connector_tools
from app.services.mcp_connector_tools import CONNECTOR_MCP_TOOLS
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, McpCaller, run_governed_mcp_tool
from app.services.mcp_infra_tools import AWS_READ_TOOLS, CONTENT_IS_DATA, KUBERNETES_READ_TOOLS, NEVER_SERVED
from app.services.tool_config import merge_tool_configs_into_project_config, upsert_tool_config
from app.tools import kubernetes
from app.tools.connectors import aws_core
from app.tools.context import ToolContext
from app.tools.definitions import get_tool_definition_metadata
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

SCOPES = ("knowledge:read", "knowledge:write")
K8S = {"k8s_api_url": "https://k8s.example.test", "k8s_token": "k8s-token-value"}
AWS = {"aws_region": "eu-central-1", "aws_access_key_id": "AKIAEXAMPLE", "aws_secret_access_key": "secret-value"}
ALLOW_LIST = {tool.name for tool in (*KUBERNETES_READ_TOOLS, *AWS_READ_TOOLS)}
EXPECTED = {
    "list_k8s_namespaces", "list_k8s_pods", "get_k8s_deployments", "list_k8s_statefulsets", "list_k8s_services",
    "list_k8s_ingresses", "list_k8s_nodes", "get_k8s_events", "get_k8s_resource_usage", "describe_k8s_pod",
    "describe_k8s_deployment", "describe_k8s_node", "list_aws_eks_clusters", "list_aws_ec2_instances",
    "list_aws_rds_instances", "list_aws_cloudwatch_alarms", "aws_read_operation", "aws_topology_snapshot",
}


@pytest.fixture(autouse=True)
def extra_tools(monkeypatch):
    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)


@pytest.fixture
def cluster(monkeypatch):
    """A fake Kubernetes API: the pods of namespace ``shop``; records each request and its bearer token."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization", "")))
        pod = {"metadata": {"name": "scoring-0", "namespace": "shop", "creationTimestamp": "2026-10-06T08:00:00Z"},
               "status": {"phase": "Running", "containerStatuses": [{"restartCount": 2, "ready": True}]},
               "spec": {"nodeName": "node-a", "containers": [{"name": "scoring"}]}}
        return httpx.Response(200, json={"items": [pod]})

    monkeypatch.setattr(kubernetes, "_k8s_transport", lambda verify: httpx.MockTransport(handler))
    monkeypatch.setattr(kubernetes, "_SA_TOKEN_PATH", kubernetes.Path("/nonexistent/sa-token"))
    return seen


def _caller(user_id: str, workspace_id: str) -> McpCaller:
    return McpCaller(user_id=user_id, grant_id=f"grant-{user_id[:8]}", scopes=SCOPES, workspace_header=workspace_id,
                     client_name="claude-code")


async def _connections(db, workspace_id: str, kubernetes_config: dict | None, aws_config: dict | None) -> None:
    """The Workspace's connections, as the admin UI stores them: tool configuration entries."""
    for tool_name, config in (("kubernetes", kubernetes_config), ("aws", aws_config)):
        await upsert_tool_config(db, tool_name=tool_name, project_id=workspace_id, config=config or {},
                                 is_active=config is not None)


async def _workspace(db, kubernetes_config: dict | None = None, aws_config: dict | None = None) -> tuple[str, str]:
    workspace_id = await seed_workspace(db)
    member_id = await seed_member(db, workspace_id=workspace_id, role="member")
    await _connections(db, workspace_id, kubernetes_config, aws_config)
    await db.commit()
    return workspace_id, member_id


async def _set(db, workspace_id: str, kubernetes_config=None, aws_config=None, *, project=None, disabled=None):
    await _connections(db, workspace_id, kubernetes_config, aws_config)
    (await db.get(Project, workspace_id)).config = project or {}
    for connector, tools in (disabled or {}).items():
        await upsert_connector_policy(db, connector_name=connector, project_id=workspace_id,
                                      policy={"disabled_tools": tools})
    await db.commit()


async def test_the_registered_set_equals_the_read_only_allow_list():
    server = FastMCP("infra-test")

    async def call(ctx, name, arguments):
        return {}

    register_connector_tools(server, call)
    registered = {tool.name: tool for tool in await server.list_tools()}
    infra = {name for name in registered if name in ALLOW_LIST or "k8s" in name or "aws" in name}
    assert ALLOW_LIST == EXPECTED and infra == EXPECTED
    assert not NEVER_SERVED & set(registered) and not NEVER_SERVED & set(CONNECTOR_MCP_TOOLS)
    for name in EXPECTED:
        metadata = get_tool_definition_metadata(name)
        assert metadata.risk == "read" and not metadata.mutates_state and not metadata.change_only, name
        assert name in CONNECTOR_MCP_TOOLS and name in EXTRA_GOVERNED_MCP_TOOLS, name
        assert "project_id" not in (registered[name].inputSchema.get("properties") or {}), name
        assert "X-Octryx-Workspace" in (registered[name].description or ""), name


async def test_a_write_or_never_served_tool_has_no_runner_whatever_the_policy(db, cluster):
    workspace_id, member_id = await _workspace(db, dict(K8S), dict(AWS))
    await _set(db, workspace_id, dict(K8S), dict(AWS), project={"tool_policy": {"allowlist": sorted(NEVER_SERVED)}})
    for name in sorted(NEVER_SERVED):
        assert name not in GOVERNED_MCP_TOOLS, name
        with pytest.raises(KeyError):
            await run_governed_mcp_tool(db, caller=_caller(member_id, workspace_id), tool_name=name,
                                        arguments={"namespace": "shop", "pod": "scoring-0"})
    assert cluster == []


async def test_kubernetes_reads_the_workspace_cluster_with_its_own_token_and_the_data_notice(db, cluster):
    workspace_id, member_id = await _workspace(db, dict(K8S))
    result = await run_governed_mcp_tool(db, caller=_caller(member_id, workspace_id), tool_name="list_k8s_pods",
                                         arguments={"namespace": "shop"})
    chat = await kubernetes.ListPods().execute(
        {"namespace": "shop"}, ToolContext(user_id=member_id, project_ids=[workspace_id], roles=["viewer"],
                                           session_id="s", project_config=dict(K8S), db=db))
    assert result == {**chat, "content_is_data": CONTENT_IS_DATA}
    assert result["pods"][0]["name"] == "scoring-0"
    assert cluster[0] == ("/api/v1/namespaces/shop/pods", "Bearer k8s-token-value")


async def test_kubernetes_gates_policy_activation_scope_and_in_cluster_token(db, cluster, monkeypatch, tmp_path):
    workspace_id, member_id = await _workspace(db, dict(K8S))
    other_id, _ = await _workspace(db, dict(K8S))
    caller = _caller(member_id, workspace_id)

    async def run(name="list_k8s_pods", caller=caller):
        return await run_governed_mcp_tool(db, caller=caller, tool_name=name, arguments={"namespace": "shop"})

    assert (await run(caller=_caller(member_id, other_id)))["state"] == "not_found", "a foreign Workspace"
    await _set(db, workspace_id, dict(K8S), disabled={"kubernetes": ["list_k8s_pods", "get_pod_logs"]})
    denied = await run()
    assert (denied["state"], denied["reason"]) == ("denied", "tool_denied_by_project_policy")
    namespaces = await run("list_k8s_namespaces")
    assert namespaces["content_is_data"] == CONTENT_IS_DATA, "a tool result always carries the data notice"
    await _set(db, workspace_id, dict(K8S), project={"disabled_connectors": ["kubernetes"]}, disabled={"kubernetes": []})
    assert (await run())["reason"] == "connector_not_active"
    await _set(db, workspace_id, {"k8s_namespace": "shop"})
    missing = await run()
    assert (missing["state"], missing["reason"]) == ("needs_configuration", "connector_not_configured")
    assert cluster == [("/api/v1/namespaces", "Bearer k8s-token-value")], "only the allowed namespace call ran"

    kubectl_runs: list[tuple] = []

    async def kubectl(*args, **kwargs):
        kubectl_runs.append(args)
        return {"items": []}

    monkeypatch.setattr(kubernetes, "_run_kubectl", kubectl)
    host_credentials = (
        {"kubeconfig_path": "/etc/octryx/kubeconfig"}, {"k8s_use_kubectl": True}, {"k8s_context": "platform"},
        {"k8s_api_url": "https://k8s.example.test"}, {**K8S, "k8s_use_kubectl": True}, {**K8S, "k8s_context": "x"},
    )
    for in_cluster in (False, True):
        if in_cluster:
            token = tmp_path / "token"
            token.write_text("platform-pod-token")
            monkeypatch.setattr(kubernetes, "_SA_TOKEN_PATH", token)  # this host runs inside a cluster
        for partial in host_credentials:
            await _set(db, workspace_id, partial)
            refused = await run()
            assert (refused["state"], refused["reason"]) == ("needs_configuration", "kubernetes_credentials_required"), (
                in_cluster, partial)
        await _set(db, workspace_id, dict(K8S))
        assert (await run())["pods"]
    assert kubectl_runs == [], "the host kubeconfig is never used over MCP"
    assert all("platform-pod-token" not in auth for _, auth in cluster), "the pod's own token never leaves"


class FakeBoto:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def client(self, service: str):
        calls = self.calls

        class Client:
            def list_clusters(self, **params):
                calls.append(service)
                return {"clusters": ["demo-eks"], "ResponseMetadata": {}}

        return Client()


async def test_aws_reads_honour_allowed_services_policy_and_activation(db, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: FakeBoto(calls))
    workspace_id, member_id = await _workspace(db, aws_config={**AWS, "aws_allowed_services": ["eks"]})
    caller = _caller(member_id, workspace_id)

    async def run(name="list_aws_eks_clusters", arguments=None):
        return await run_governed_mcp_tool(db, caller=caller, tool_name=name, arguments=arguments or {})

    result = await run()
    assert result == {"count": 1, "clusters": ["demo-eks"], "content_is_data": CONTENT_IS_DATA} and calls == ["eks"]
    await _set(db, workspace_id, aws_config={**AWS, "aws_allowed_services": ["ec2"]})
    blocked = await run()
    assert "not allowed" in blocked["error"] and blocked["content_is_data"] == CONTENT_IS_DATA and calls == ["eks"]
    read = await run("aws_read_operation", {"service": "eks", "operation": "list-clusters"})
    assert read["error"] == "AWS service 'eks' is not allowed"
    await _set(db, workspace_id, aws_config=dict(AWS), disabled={"aws": ["aws_read_operation", "aws_action_operation"]})
    assert (await run("aws_read_operation", {"service": "ec2", "operation": "describe-instances"}))["reason"] == (
        "tool_denied_by_project_policy")
    await _set(db, workspace_id)
    missing = await run()
    assert (missing["state"], missing["reason"]) == ("needs_configuration", "connector_not_configured")
    assert calls == ["eks"]


async def test_aws_over_mcp_needs_workspace_credentials_or_the_audited_admin_opt_in(db, monkeypatch):
    """Region or profile alone would let boto3 use the platform host's default chain: refused unless opted in."""
    calls: list[str] = []
    monkeypatch.setattr(aws_core, "_get_boto_session", lambda context: FakeBoto(calls))

    async def assume(context, session):
        if context.project_config.get("aws_role_arn"):
            calls.append("sts")
        return session

    monkeypatch.setattr(aws_core, "_assume_role_if_needed", assume)
    workspace_id, member_id = await _workspace(db, aws_config={"aws_region": "eu-central-1"})
    caller = _caller(member_id, workspace_id)

    async def run():
        return await run_governed_mcp_tool(db, caller=caller, tool_name="list_aws_eks_clusters", arguments={})

    async def platform_audits() -> int:
        rows = (await db.execute(select(AuditLog).where(
            AuditLog.action == "mcp.connector.platform_credentials_used"))).scalars().all()
        assert all(row.resource_id == workspace_id and row.details["tool_name"] == "list_aws_eks_clusters"
                   and row.details["connection_id"] == "default" for row in rows)
        return len(rows)

    region = {"aws_region": "eu-central-1"}
    for host in (region, {**region, "aws_profile": "platform"}, {**region, "aws_access_key_id": "AKIAEXAMPLE"},
                 {**region, "allow_platform_credentials": False}):
        await _set(db, workspace_id, aws_config=host)
        refused = await run()
        assert (refused["state"], refused["reason"]) == ("needs_configuration", "aws_credentials_required"), host
    # The opt-in is an admin tool-configuration key: Project.config can neither hold nor supply it.
    await _set(db, workspace_id, aws_config=region, project={"allow_platform_credentials": True})
    assert "allow_platform_credentials" not in await merge_tool_configs_into_project_config(
        db, workspace_id, {"allow_platform_credentials": True})
    assert (await run())["reason"] == "aws_credentials_required"
    assert calls == [] and await platform_audits() == 0

    for own in (dict(AWS), {**region, "aws_role_arn": "arn:aws:iam::123456789012:role/WorkspaceRead"}):
        await _set(db, workspace_id, aws_config=own)
        assert (await run())["clusters"] == ["demo-eks"], own
    await _set(db, workspace_id, aws_config={**AWS, "allow_platform_credentials": True})
    assert (await run())["clusters"] == ["demo-eks"]
    assert await platform_audits() == 0, "own credentials: the opt-in is not used, nothing to audit"
    await _set(db, workspace_id, aws_config={**region, "allow_platform_credentials": True})
    assert (await run())["clusters"] == ["demo-eks"]
    assert await platform_audits() == 1 and calls == ["eks", "sts", "eks", "eks", "eks"]
    await _set(db, workspace_id, aws_config={**region, "allow_platform_credentials": True},
               project={"disabled_connectors": ["aws"]})
    assert (await run())["reason"] == "connector_not_active", "the opt-in never overrides a deactivation"
    with pytest.raises(ValueError, match="must be a boolean"):
        await upsert_tool_config(db, tool_name="aws", project_id=workspace_id,
                                 config={**region, "allow_platform_credentials": "yes"})


async def test_each_registered_tool_mirrors_the_chat_schema_and_forwards_every_argument():
    from app.tools.definitions import get_all_definitions

    chat = get_all_definitions()
    forwarded: dict[str, dict] = {}

    async def call(ctx, name, arguments):
        forwarded[name] = arguments
        return {}

    server = FastMCP("infra-forward-test")
    register_connector_tools(server, call)
    registered = {tool.name: tool for tool in await server.list_tools()}
    samples = {"string": "x", "integer": 3, "boolean": True, "array": ["x"]}
    for name in EXPECTED:
        chat_properties = chat[name]["function"].get("parameters", {}).get("properties", {})
        properties = registered[name].inputSchema.get("properties") or {}
        assert set(properties) == set(chat_properties), name
        arguments = {key: samples.get(spec.get("type"), {"k": "v"}) for key, spec in chat_properties.items()}
        if name == "aws_topology_snapshot":
            arguments["diagram_detail"] = "compact"
        await server.call_tool(name, arguments)
        assert forwarded[name] == arguments, name
