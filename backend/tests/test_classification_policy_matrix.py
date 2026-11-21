"""The classification policy matrix — admin API, audit, and every rule narrowing at its decision point.

The default behaviour is pinned separately (``test_classification_policy_defaults.py``, which also passes on
the commit before the matrix). Here each rule is changed for one level and the existing decision point is
asked: seat, the inbound gateway and Knowledge model admission, the reranker and remote embeddings, the chat
tool listing and dispatch, the MCP call and ``tools/list``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.services import mcp_knowledge_protocol
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY
from app.services.knowledge.embedding.port import EmbeddingError
from app.services.knowledge.embedding.selection import admit_space, embedding_config_from_environment
from app.services.knowledge.rerank.admission_state import reranker_admission
from app.services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from app.services.mcp_governed_knowledge import GOVERNED_MCP_TOOLS, McpCaller, run_governed_mcp_tool
from app.services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from app.services.model_gateway.inbound.admission import InboundAdmission, admit_inbound_call
from app.services.project import get_project_config
from app.tools import kubernetes
from app.tools.context import ToolContext
from app.tools.registry import _run_governed_tool_checks
from app.tools.visibility import filter_tool_definitions_by_visibility, tool_visibility_decision
from tests.classification_policy_matrix_support import (
    REMOTE_SPACE,
    RERANKER,
    _bearer,
    _catalog_clearance,
    _gateway,
    _matrix,
    _workspace,
)
from tests.knowledge_evidence_seed_support import seed_member
from tests.model_gateway.conftest import ALIAS, gateway_runtime

CONNECTORS_ON = {"jira_enabled": True, "confluence_enabled": True, "aws_enabled": True}


def _context(config: dict) -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", project_config=config)


@pytest.fixture
def extra_tools(monkeypatch):
    for name, entry in EXTRA_GOVERNED_MCP_TOOLS.items():
        monkeypatch.setitem(GOVERNED_MCP_TOOLS, name, entry)


# --- seat ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seat_follows_the_level_rules(client, db):
    workspace_id = await _workspace(db, agent_gateway_policy={"seat_mode": "allowed"})
    public_id = await _workspace(db, "public", agent_gateway_policy={"seat_mode": "allowed"})

    await _matrix(db, seat_allowed=False)
    forbidden = await workspace_seat_decision(db, workspace_id)
    await _matrix(db, requires_governed_routing=True)
    governed = await workspace_seat_decision(db, workspace_id)
    await _matrix(db, "confidential", seat_allowed=True)
    confidential = await workspace_seat_decision(db, await _workspace(db, "confidential",
                                                                        agent_gateway_policy={"seat_mode": "allowed"}))

    assert (forbidden.allowed, forbidden.reason) == (False, "seat_classification_too_sensitive")
    assert (governed.allowed, governed.reason) == (False, "seat_classification_requires_governed_routing")
    assert confidential.allowed is True
    assert (await workspace_seat_decision(db, public_id)).allowed is True
    owner = await seed_member(db, workspace_id=workspace_id, role="owner")
    await db.commit()
    seat = (await client.get(f"/api/v1/workspaces/{workspace_id}/agent-gateway/seat-mode",
                             headers=await _bearer(owner))).json()
    assert (seat["in_effect"], seat["reason"]) == (True, None)  # the last write only changed confidential


# --- models -------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_level_alias_list_narrows_the_inbound_and_knowledge_model_admission(db):
    await _gateway(db)
    workspace_id = await _workspace(db)
    public_id = await _workspace(db, "public")

    await _catalog_clearance(db, "public")
    inbound = await admit_inbound_call(db, workspace_id=workspace_id, alias=ALIAS, declares_tools=False)
    knowledge = await admit_runtimes_for_dispatch(db, [gateway_runtime()], project_ids=workspace_id,
                                                  owner="knowledge_graph_runtime")
    public = await admit_inbound_call(db, workspace_id=public_id, alias=ALIAS, declares_tools=False)
    # A scope that contains the narrowed level carries that level's list into the driver admission.
    scoped = await admit_runtimes_for_dispatch(db, [gateway_runtime()], project_ids=[public_id, workspace_id],
                                               owner="knowledge_graph_runtime")
    await _catalog_clearance(db, "internal")
    listed = await admit_inbound_call(db, workspace_id=workspace_id, alias=ALIAS, declares_tools=False)
    await _catalog_clearance(db, "internal", enabled=False)
    disabled = await admit_inbound_call(db, workspace_id=workspace_id, alias=ALIAS, declares_tools=False)

    assert inbound.reason == "model_alias_not_allowed_for_classification"
    assert not knowledge.allowed and knowledge.reason == "model_alias_not_allowed_for_classification"
    assert isinstance(public, InboundAdmission) and isinstance(listed, InboundAdmission)
    assert not scoped.allowed and scoped.reason == "model_alias_not_allowed_for_classification"
    assert disabled.reason == "model_alias_not_allowed_for_classification"


# --- reranker and remote embeddings --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reranker_and_remote_embeddings_can_be_forbidden_per_level(db, monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER", RERANKER)
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", REMOTE_SPACE)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    workspace_id = await _workspace(db)
    space = embedding_config_from_environment().space

    await _matrix(db, reranker_allowed=False)
    reranker = await reranker_admission(db, project_id=workspace_id)
    await admit_space(db, project_id=workspace_id, space=space)  # embeddings untouched by the reranker rule
    await _matrix(db, remote_embeddings_allowed=False)
    with pytest.raises(EmbeddingError) as embeddings:
        await admit_space(db, project_id=workspace_id, space=space)

    assert (reranker["state"], reranker["hold_reason"]) == ("denied", "classification_policy_reranker_forbidden")
    assert (embeddings.value.state.value, embeddings.value.reason) == (
        "denied", "classification_policy_remote_embeddings_forbidden")
    assert (await reranker_admission(db, project_id=workspace_id))["state"] == "ok"


# --- tools: chat ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_connector_family_set_to_none_is_hidden_and_refused_in_chat(db):
    workspace_id = await _workspace(db, **CONNECTORS_ON)
    await _matrix(db, connectors={"kubernetes": "none"})
    config = await get_project_config(workspace_id, db)
    definitions = [{"function": {"name": name}} for name in ("list_k8s_pods", "search_jira_tickets", "knowledge_search")]

    refused = await _run_governed_tool_checks("list_k8s_pods", {"namespace": "shop"}, _context(config))

    assert [item["function"]["name"] for item in filter_tool_definitions_by_visibility(definitions, config)] == [
        "search_jira_tickets", "knowledge_search"]
    decision = tool_visibility_decision("run_kubectl", config)
    assert (decision.visible, decision.reason, decision.policy) == (
        False, "classification_connector_denied", "classification_policy")
    assert refused["policy"] == "classification_policy" and refused["reason"] == "classification_connector_denied"
    assert "kubernetes" in refused["error"]


@pytest.mark.asyncio
async def test_a_read_only_family_hides_its_write_tools_and_write_subcommands(db):
    workspace_id = await _workspace(db, **CONNECTORS_ON)
    await _matrix(db, connectors={"jira": "read", "kubernetes": "read"})
    config = await get_project_config(workspace_id, db)

    write = await _run_governed_tool_checks("create_jira_ticket", {}, _context(config))
    apply = await _run_governed_tool_checks("run_kubectl", {"args": "apply -f x.yaml"}, _context(config))
    get = await _run_governed_tool_checks("run_kubectl", {"args": ["get", "pods"]}, _context(config))

    assert tool_visibility_decision("search_jira_tickets", config).visible
    assert not tool_visibility_decision("create_jira_ticket", config).visible
    assert tool_visibility_decision("run_kubectl", config).visible  # read subcommands stay available
    assert write["reason"] == apply["reason"] == "classification_connector_read_only"
    assert get is None or get.get("policy") != "classification_policy"


@pytest.mark.asyncio
async def test_log_masking_blocks_the_log_reading_tools_only(db):
    workspace_id = await _workspace(db, **CONNECTORS_ON)
    await _matrix(db, log_masking_required=True)
    config = await get_project_config(workspace_id, db)

    async def reason(tool: str, params: dict) -> str | None:
        refused = await _run_governed_tool_checks(tool, params, _context(config))
        return refused.get("reason") if refused and refused.get("policy") == "classification_policy" else None

    assert not tool_visibility_decision("get_pod_logs", config).visible
    assert not tool_visibility_decision("get_aws_lambda_logs", config).visible
    assert tool_visibility_decision("list_k8s_pods", config).visible
    assert await reason("get_aws_ec2_logs", {}) == "log_masking_not_available"
    assert await reason("run_kubectl", {"args": "logs pod-1"}) == "log_masking_not_available"
    assert await reason("aws_read_operation", {"service": "logs", "operation": "get-log-events"}) == (
        "log_masking_not_available")
    assert await reason("aws_read_operation", {"service": "ec2", "operation": "describe-instances"}) is None
    assert await reason("run_kubectl", {"args": "get pods"}) is None


@pytest.mark.asyncio
async def test_the_section_comes_from_the_row_classification_never_from_stored_config(db):
    spoofed = {"level": "public", "connectors": {"kubernetes": "read_write"}, "log_masking_required": False}
    workspace_id = await _workspace(db, **{CLASSIFICATION_TOOL_POLICY_KEY: spoofed})
    unclassified = await _workspace(db, None, **{CLASSIFICATION_TOOL_POLICY_KEY: {"level": "internal",
                                                                                   "connectors": {"jira": "none"}}})
    await _matrix(db, connectors={"kubernetes": "none", "jira": "none"})

    config = await get_project_config(workspace_id, db)
    unclassified_config = await get_project_config(unclassified, db)

    assert config[CLASSIFICATION_TOOL_POLICY_KEY]["level"] == "internal"
    assert not tool_visibility_decision("list_k8s_pods", config).visible
    assert unclassified_config[CLASSIFICATION_TOOL_POLICY_KEY] == {"level": None}
    assert tool_visibility_decision("list_k8s_pods", unclassified_config).visible


# --- tools: MCP / octryx-claude Knowledge MCP ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_lists_and_refuses_what_the_level_does_not_admit(db, extra_tools, monkeypatch):
    workspace_id = await _workspace(db)
    member = await seed_member(db, workspace_id=workspace_id, role="member")
    await db.commit()
    await _matrix(db, connectors={"kubernetes": "none"})
    caller = McpCaller(user_id=member, grant_id="grant-1", scopes=("knowledge:read",), workspace_header=workspace_id,
                       client_name="claude-code")
    monkeypatch.setattr(kubernetes, "_k8s_transport", lambda verify: pytest.fail("no cluster call"))

    refused = await run_governed_mcp_tool(db, caller=caller, tool_name="list_k8s_pods", arguments={})

    async def connection_workspace(server, session):
        return workspace_id

    @asynccontextmanager
    async def test_session():
        yield db

    monkeypatch.setattr(mcp_knowledge_protocol, "_connection_workspace", connection_workspace)
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", test_session)
    server = mcp_knowledge_protocol.build_knowledge_mcp_server()
    names = {tool.name for tool in await server.list_tools()}

    assert (refused["state"], refused["reason"]) == ("denied", "classification_connector_denied")
    assert "list_k8s_pods" not in names and "describe_k8s_pod" not in names
    assert "aws_read_operation" in names and "knowledge_projects" in names
