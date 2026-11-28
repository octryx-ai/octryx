"""The default classification policy matrix gives the expected decision at every covered entry point, for every
level."""

from __future__ import annotations

import uuid

import pytest

from app.models import Project
from app.services.agent_gateway.seat_policy import workspace_seat_decision
from app.services.knowledge.embedding.port import EmbeddingError
from app.services.knowledge.embedding.selection import admit_space, embedding_config_from_environment
from app.services.knowledge.rerank.admission_state import reranker_admission
from app.services.mcp_connector_tools import CONNECTOR_MCP_TOOLS
from app.services.model_gateway.dispatch_admission import admit_runtimes_for_dispatch
from app.services.model_gateway.inbound.admission import InboundAdmission, admit_inbound_call
from app.services.model_gateway.inbound.refusals import InboundRefusal
from app.services.project import get_project_config
from app.services.secret import set_secret_value
from app.tools.context import ToolContext
from app.tools.registry_governance import _run_governed_tool_checks
from app.tools.visibility import tool_visibility_decision
from tests.model_gateway.conftest import ALIAS, GATEWAY_HOST, VIRTUAL_KEY, gateway_provider, gateway_runtime

LEVELS = ("public", "internal", "confidential", "restricted", "secret")
SEAT_LEVELS = {"public", "internal"}
GATEWAY_LEVELS = {"public", "internal"}
RERANKER = "bedrock_cohere_rerank35_v1"
REMOTE_SPACE = "bedrock_titan2_1024_v1"
CONNECTORS_ON = {"jira_enabled": True, "confluence_enabled": True, "aws_enabled": True,
                 "servicenow_enabled": True, "bitbucket_enabled": True}
TOOLS = (
    "list_k8s_pods", "get_pod_logs", "run_kubectl", "aws_read_operation", "get_aws_ec2_logs",
    "start_aws_ec2_instances", "list_servicenow_incidents", "search_jira_tickets", "create_jira_ticket",
    "search_confluence", "update_confluence_page", "list_bitbucket_repositories", "create_bitbucket_pull_request",
)


async def _workspace(db, level: str | None, **config) -> str:
    project = Project(
        id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:8]}", is_active=True,
        config={
            "model_policy": {"allowed_aliases": [ALIAS]},
            **({"data_policy": {"classification": level}} if level else {}),
            **config,
        },
    )
    db.add(project)
    await db.commit()
    return project.id


@pytest.fixture
def remote_models(monkeypatch):
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_RERANKER", RERANKER)
    monkeypatch.setenv("OCTRYX_KNOWLEDGE_EMBEDDING_SPACE", REMOTE_SPACE)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("level", LEVELS)
async def test_seat_is_allowed_below_confidential_only(db, level):
    allowed = await _workspace(db, level, agent_gateway_policy={"seat_mode": "allowed"})
    governed = await _workspace(
        db, level, agent_gateway_policy={"seat_mode": "allowed", "requires_governed_routing": True}
    )

    decision = await workspace_seat_decision(db, allowed)
    governed_decision = await workspace_seat_decision(db, governed)

    if level in SEAT_LEVELS:
        assert (decision.allowed, decision.reason) == (True, "")
        assert governed_decision.reason == "seat_requires_governed_routing"
    else:
        assert (decision.allowed, decision.reason) == (False, "seat_classification_too_sensitive")
        assert governed_decision.reason == "seat_classification_too_sensitive"


@pytest.mark.asyncio
async def test_an_unclassified_workspace_never_gets_seat(db):
    decision = await workspace_seat_decision(db, await _workspace(db, None, agent_gateway_policy={"seat_mode": "allowed"}))

    assert (decision.allowed, decision.reason) == (False, "seat_classification_unresolved")


@pytest.mark.asyncio
@pytest.mark.parametrize("level", LEVELS)
async def test_gateway_models_follow_the_alias_data_policy_class(db, level):
    workspace_id = await _workspace(db, level)
    secret = await set_secret_value(db, tool_name="litellm_gateway", field_name="virtual_key", project_id=None,
                                    value=VIRTUAL_KEY)
    db.add(gateway_provider(name=f"litellm-{uuid.uuid4().hex[:6]}", api_key_secret_ref=secret.id,
                            endpoint_url=f"https://{GATEWAY_HOST}"))
    await db.commit()

    inbound = await admit_inbound_call(db, workspace_id=workspace_id, alias=ALIAS, declares_tools=True)
    knowledge = await admit_runtimes_for_dispatch(
        db, [gateway_runtime()], project_ids=workspace_id, owner="knowledge_graph_runtime"
    )

    if level in GATEWAY_LEVELS:
        driver = knowledge.runtimes[0].get("project_model_admission")
        assert isinstance(inbound, InboundAdmission)
        assert driver is not None and driver.decide_data_policy("internal").allowed
        assert knowledge.allowed and driver.decide(ALIAS).allowed
    else:
        # The level's model list is derived from the clearance, so an alias cleared below the
        # level is refused at the model admission already (before the data-policy gate); both deny.
        assert isinstance(inbound, InboundRefusal) and inbound.reason == "model_alias_not_allowed_for_classification"
        assert not knowledge.allowed and knowledge.reason == "model_alias_not_allowed_for_classification"


@pytest.mark.asyncio
@pytest.mark.parametrize("level", LEVELS)
async def test_reranker_and_remote_embeddings_follow_their_data_policy_class(db, remote_models, level):
    workspace_id = await _workspace(db, level)

    reranker = await reranker_admission(db, project_id=workspace_id)
    try:
        await admit_space(db, project_id=workspace_id, space=embedding_config_from_environment().space)
        embeddings = "ok"
    except EmbeddingError as error:
        embeddings = error.reason

    if level in GATEWAY_LEVELS:
        assert (reranker["state"], embeddings) == ("ok", "ok")
    else:
        assert (reranker["state"], reranker["hold_reason"]) == ("denied", "data_policy_class_insufficient")
        assert embeddings == "data_policy_class_insufficient"


@pytest.mark.asyncio
@pytest.mark.parametrize("level", (*LEVELS, None))
async def test_every_connector_tool_stays_listed_and_callable_at_every_level(db, level):
    config = await get_project_config(await _workspace(db, level, **CONNECTORS_ON), db)
    context = ToolContext(user_id="u", project_ids=[], roles=[], session_id="s", project_config=config)

    for tool in TOOLS:
        assert tool_visibility_decision(tool, config).visible, tool
    for tool, params in (("run_kubectl", {"args": "logs pod-1"}), ("run_kubectl", {"args": ["apply", "-f", "x"]}),
                         ("aws_read_operation", {"service": "logs", "operation": "filter-log-events"})):
        refusal = await _run_governed_tool_checks(tool, params, context)
        assert refusal is None or refusal.get("policy") not in {"connector_activation", "classification_policy"}, (
            tool, refusal
        )
    assert {"list_k8s_pods", "aws_read_operation", "search_jira_tickets"} <= set(CONNECTOR_MCP_TOOLS)
