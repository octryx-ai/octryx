"""Reproductions from an external risk review of the agent boundaries: a platform agent runs only its published
revision, in the octryx view, the reviewer, the device contract, the device hooks and the gateway admission.

Ported in substance (only formatting changed). The fuller cases live next to the code they
cover (``test_platform_agent_published_execution.py``, ``test_workspace_agents_d5.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.models import AgentDefinition, AgentDefinitionRevision, User
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.agent_gateway.contract import HEADER_GATEWAY_REASON, HEADER_GATEWAY_STATE
from app.services.workflow_runs.octryx.agent_view import agent_view
from app.services.workflow_runs.review.reviewer_agent import reviewer_setup
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


def _gateway_request():
    """A gateway request as the handler decorator leaves it: with the request's content outcome."""
    from app.services.content_routing.gateway_outcome import GatewayOutcome

    return SimpleNamespace(headers={}, state=SimpleNamespace(gateway_outcome=GatewayOutcome()))


async def _row_and_published(db, key: str):
    row = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == key))).scalar_one()
    published = (await db.execute(select(AgentDefinitionRevision).where(
        AgentDefinitionRevision.definition_id == row.id, AgentDefinitionRevision.status == "published"))
    ).scalars().first()
    return row, published


@pytest.mark.parametrize("key", ["engineer", "assistant"])
async def test_unpublished_instructions_never_reach_octryx(db, key):
    row, published = await _row_and_published(db, key)
    approved = published.snapshot["definition"]["system_prompt"]
    row.system_prompt = "UNAPPROVED_DRAFT_CANARY"
    draft = await create_draft_revision(db, definition=row, created_by=row.owner_id)
    view = await agent_view(db, key)
    assert view["instructions"] == approved and view["version"] == published.revision_number, {
        "draft": draft.status, "view": view}


async def test_unpublished_reviewer_instructions_never_run(db, monkeypatch):
    row, published = await _row_and_published(db, "reviewer")
    approved = published.snapshot["definition"]["system_prompt"]
    row.system_prompt = "UNAPPROVED_REVIEWER_DRAFT_CANARY"
    await create_draft_revision(db, definition=row, created_by=row.owner_id)

    async def no_author(*args):
        return ""

    monkeypatch.setattr("app.services.workflow_runs.review.reviewer_agent._author_model", no_author)
    setup = await reviewer_setup(db, None)
    assert setup.instructions == approved


@pytest.mark.usefixtures("public_source_dns")
async def test_unpublished_phase_agent_refuses_native_device_read(db):
    from app.services.workflow_runs.octryx.hooks import run_pre_tool_use
    from tests.test_octryx_platform_agent import _run

    _run_row, session = await _run(db, "engineer")
    agent = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == "engineer"))).scalar_one()
    await db.execute(update(AgentDefinitionRevision).where(AgentDefinitionRevision.definition_id == agent.id,
                                                           AgentDefinitionRevision.status == "published")
                     .values(status="superseded"))
    await db.flush()
    decision, *_rest = await run_pre_tool_use(db, session=session, policy=None,
                                              hook_input={"tool_name": "Read", "tool_input": {"file_path": "README.md"}})
    assert decision is not None and decision.decision == "deny", decision


async def test_published_agent_tools_deny_is_in_the_device_contract(db):
    from app.services.workflow_runs.octryx.contract import run_contract
    from tests.prompt_catalog_publish_support import second_admin
    from tests.test_octryx_platform_agent import _run

    row = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == "engineer"))).scalar_one()
    row.tools_deny_json = '["knowledge_search"]'
    draft = await create_draft_revision(db, definition=row, created_by=row.owner_id)
    reviewer = await second_admin(db)
    await publish_revision(db, revision=draft, published_by=reviewer.id)
    run, _session = await _run(db, "engineer")
    tools = (await run_contract(db, run))["phase"]["tools"]
    assert "knowledge_search" not in tools["allow"] and "knowledge_search" in tools["deny"], tools


async def test_coding_admission_checks_served_model_not_group_label(db, monkeypatch):
    from app.services.model_gateway.inbound import service
    from tests.test_octryx_platform_agent import _run

    run, session = await _run(db, "engineer")
    user = await db.get(User, run.requested_by)
    identity = SimpleNamespace(user=user, workspace_id=run.project_id, session_key="canary-key")
    # Upstream model groups are deployment labels, not model family identifiers.
    admitted = SimpleNamespace(entry=SimpleNamespace(model_group="team-coding",
                                                     served_model_ids=frozenset({"claude-3-5-haiku-20241022"})))

    async def resolve(*args):
        return identity

    async def get_session(*args):
        return session

    async def body(*args, **kwargs):
        return {"model": "alias-coding", "messages": []}

    async def touch(*args, **kwargs):
        return None

    async def admit(*args, **kwargs):
        return admitted

    monkeypatch.setattr(service, "resolve_gateway_identity", resolve)
    monkeypatch.setattr(service, "get_or_create_gateway_session", get_session)
    monkeypatch.setattr(service, "_read_body", body)
    monkeypatch.setattr(service, "touch_presence", touch)
    monkeypatch.setattr(service, "admit_inbound_call", admit)
    # No model is released per kind of work; every model the Workspace admits may do
    # any phase's work, whatever its group label or served model.
    result = await service.admitted_request(_gateway_request(), db)
    assert isinstance(result, tuple), "an admitted model is refused for its kind of work"
    assert result[1] == session.id
    # Still protected: a phase agent that cannot run refuses the session's call with its reason.
    engineer = (await db.execute(select(AgentDefinition).where(AgentDefinition.builtin_key == "engineer"))).scalar_one()
    engineer.is_active = False
    await db.commit()
    refused = await service.admitted_request(_gateway_request(), db)
    assert not isinstance(refused, tuple)
    assert refused.headers[HEADER_GATEWAY_STATE] == "needs_configuration"
    assert refused.headers[HEADER_GATEWAY_REASON] == "agent_inactive"
