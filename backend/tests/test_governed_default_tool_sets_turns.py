"""A plain chat turn gets the chat set filtered by visibility, and a change agent outside a workflow run gets the read-only set."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agent.runtime_defaults import CODING_WRITE_TOOLS
from app.models import Project, User
from app.services.governed_default_tool_sets import governed_default_tool_set
from tests.connection_support import connect
from tests.governed_default_tool_sets_support import _prepare


@pytest.mark.asyncio
async def test_a_plain_chat_turn_gets_the_chat_set_filtered_by_visibility(db, tmp_path: Path) -> None:
    """Chat = client parity: the Workspace's Jira and Confluence reads are offered to a plain chat turn."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"w22-chat-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    for tool in ("jira", "confluence"):
        await connect(db, tool, project.id)
    await db.commit()

    prepared = await _prepare(db, tmp_path, project, admin, "diagnosis")

    offered = {definition["function"]["name"] for definition in prepared.tool_definitions}
    offered |= set(prepared.tool_context.deferred_tool_catalog or {})  # listed by name, loaded with tool_search
    assert prepared.context_plan.tool_surface_set == "diagnosis.v10"
    # The chat's one confirmation per request comes with its writes (chat_write_plan), outside the governed set.
    assert offered - {"propose_write_plan"} <= set(governed_default_tool_set("diagnosis").tools)
    assert {"select_workflow", "knowledge_search", "search_jira_tickets", "get_jira_ticket",
            "search_confluence"} <= offered
    # Reads run without a confirmation; only writes go through the chat's write plan.
    from app.tools.definitions import get_tool_definition_metadata

    for read in ("search_jira_tickets", "get_jira_ticket", "search_confluence"):
        metadata = get_tool_definition_metadata(read)
        assert (metadata.risk, metadata.approval_required, metadata.mutates_state) == ("read", False, False), read
    # Connector visibility: Bitbucket has no connection here, so its read tools are not offered.
    assert "list_recent_bitbucket_commits" not in offered
    assert not offered & CODING_WRITE_TOOLS


@pytest.mark.asyncio
async def test_a_change_agent_outside_a_workflow_run_gets_the_read_only_set(db, tmp_path: Path) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"w22-change-{uuid.uuid4().hex[:6]}", config={}, is_active=True)
    db.add(project)
    await db.commit()

    # Chat is strictly read-only: a change-capable blueprint outside a workflow run is capped to
    # read_only and gets the diagnosis set (the change set is a run phase's, see the phase turn tests).
    blueprint = {"name": "Coder", "capability_type": "change", "steps": []}
    prepared = await _prepare(db, tmp_path, project, admin, "change", agent_definition=blueprint)

    names = {definition["function"]["name"] for definition in prepared.tool_definitions}
    assert prepared.context_plan.tool_surface_set == "diagnosis.v10"
    assert not {"edit_workspace_file", "write_workspace_file"} & names
