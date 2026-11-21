"""Session links stay in the item workspace and foreign workflows are refused while own and global workflows stay usable."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Session, WorkChangePlan, WorkItemWorkflowDefinition
from app.services import knowledge_graph, mcp_secure_work_tools, mcp_work_targets
from app.services.secure_work.platform_item_sessions import _link_session_in_graph, link_session_to_work_item
from tests.mcp_native_support import mcp_call, native_token
from tests.mcp_work_grant_scope_support import WORK_SCOPES, _error_text, _item, _snapshot, spies, world  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_session_link_validates_the_secondary_session(world):  # noqa: F811
    db, member = world.db, world.member
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=None)
    item_a, sessions = world.items["a"], world.sessions
    before = await _snapshot(db)
    for ref in (
        sessions["other_a"].metadata_["client_session_id"],  # another user's session, same workspace
        sessions["own_b"].metadata_["client_session_id"],  # own session, other workspace
        "cc-unknown-session",
    ):
        text = _error_text(
            await mcp_call(token, "work_item_link_session", {"work_item": item_a.id, "client_session_id": ref})
        )
        assert f"Session not found: {ref}" in text
    ambiguous = sessions["dup_1"].metadata_["client_session_id"]
    text = _error_text(
        await mcp_call(token, "work_item_link_session", {"work_item": item_a.id, "client_session_id": ambiguous})
    )
    assert "ambiguous" in text
    assert await _snapshot(db) == before

    own = sessions["own_a"].metadata_["client_session_id"]
    linked = await mcp_call(token, "work_item_link_session", {"work_item": item_a.id, "client_session_id": own})
    assert linked["platform_session_found"] is True and linked["linked_sessions"] == 1
    metadata = (await db.execute(select(Session.metadata_).where(Session.id == sessions["own_a"].id))).scalar_one()
    assert metadata["work_item_keys"] == [item_a.source_key]


async def test_session_link_graph_edge_stays_in_the_item_workspace(db, world, monkeypatch):  # noqa: F811
    item_a = world.items["a"]
    client_session_id = f"cc-graph-{uuid.uuid4().hex[:8]}"
    edges: list[dict] = []

    async def _ticket(_db, *, project_id, alias):
        return SimpleNamespace(id=f"ticket-{project_id}")

    async def _edge(_db, **kwargs):
        edges.append(kwargs)

    monkeypatch.setattr(knowledge_graph, "resolve_node_by_alias", _ticket)
    monkeypatch.setattr(knowledge_graph, "upsert_edge", _edge)
    from app.models import KnowledgeGraphNode

    db.add(
        KnowledgeGraphNode(project_id=world.b, node_type="agent_session", node_key=f"agent-session-{client_session_id}")
    )
    await db.flush()
    await _link_session_in_graph(db, item=item_a, client_session_id=client_session_id, scoped=True)
    assert edges == []  # the only session node lives in another workspace

    await _link_session_in_graph(db, item=item_a, client_session_id=client_session_id, scoped=False)
    assert len(edges) == 1

    edges.clear()
    db.add(
        KnowledgeGraphNode(project_id=world.a, node_type="agent_session", node_key=f"agent-session-{client_session_id}")
    )
    await db.flush()
    await _link_session_in_graph(db, item=item_a, client_session_id=client_session_id, scoped=True)
    assert len(edges) == 1 and edges[0]["project_id"] == world.a


async def test_legacy_session_link_path_is_unchanged(db, world):  # noqa: F811
    item = world.items["a"]
    result = await link_session_to_work_item(
        db, item=item, client_session_id="cc-not-ingested-yet", current_user=world.member
    )
    assert result["platform_session_found"] is False and result["linked_sessions"] == 1


# --- Secondary configuration targets (root probes promoted) -------------------------------------------


async def test_foreign_workflows_are_refused_before_transition_generate_and_decide(world, spies, monkeypatch):  # noqa: F811
    db, member, workflows = world.db, world.member, world.workflows
    item_a = world.items["a"]
    foreign_plan = WorkChangePlan(
        work_item_id=item_a.id,
        version=2,
        status="ready_for_review",
        title="plan stored with a foreign workflow",
        created_by=world.admin.id,
        workflow_id=workflows["b"],
    )
    db.add(foreign_plan)
    await db.commit()
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    before = await _snapshot(db)

    supplied = {"work_item": item_a.id, "to_state": "development", "workflow_id": workflows["b"]}
    assert "404: Workflow definition not found" in _error_text(await mcp_call(token, "work_item_transition", supplied))
    generate = {"work_item": item_a.id, "payload": {"workflow_id": workflows["b"]}}
    assert "404: Workflow definition not found" in _error_text(await mcp_call(token, "change_plan_generate", generate))
    decide = {"change_plan_id": foreign_plan.id, "action": "reject", "reason": "probe"}
    assert "workflow is not available" in _error_text(await mcp_call(token, "change_plan_decide", decide))

    # The default lookup may fall back to any active workflow: a foreign result counts as none.
    async def _foreign_default(_db, _item):  # noqa: F811
        return await _db.get(WorkItemWorkflowDefinition, workflows["b"])

    monkeypatch.setattr(mcp_work_targets, "default_workflow_for_item", _foreign_default)
    default = {"work_item": item_a.id, "to_state": "development"}
    assert "No active workflow definition" in _error_text(await mcp_call(token, "work_item_transition", default))

    assert spies == []
    assert await _snapshot(db) == before


async def test_own_and_global_workflows_stay_usable(world, monkeypatch):  # noqa: F811
    db, member, workflows = world.db, world.member, world.workflows
    item_a = world.items["a"]
    seen: list[tuple[str, str | None]] = []

    async def _transition(_db, *, workflow_id, **_kwargs):
        seen.append(("transition", workflow_id))
        return {"work_state": "development", "preview": {"jira_sync_preview": {}}}

    async def _generate(_db, *, payload, **_kwargs):
        seen.append(("generate", payload.get("workflow_id")))
        return {"id": "p", "version": 3, "status": "ready_for_review"}

    async def _global_default(_db, _item):  # noqa: F811
        return await _db.get(WorkItemWorkflowDefinition, workflows["global"])

    monkeypatch.setattr(mcp_secure_work_tools, "transition_work_item", _transition)
    monkeypatch.setattr(mcp_secure_work_tools, "generate_change_plan", _generate)
    monkeypatch.setattr(mcp_work_targets, "default_workflow_for_item", _global_default)
    token = await native_token(db, user_id=member.id, scopes=WORK_SCOPES, project_ids=[world.a])
    for workflow_id in (workflows["a"], workflows["global"], None):
        arguments = {"work_item": item_a.id, "to_state": "development"}
        if workflow_id:
            arguments["workflow_id"] = workflow_id
        assert not (await mcp_call(token, "work_item_transition", arguments)).get("isError")
    for workflow_id in (workflows["a"], workflows["global"]):
        payload = {"work_item": item_a.id, "payload": {"workflow_id": workflow_id}}
        assert not (await mcp_call(token, "change_plan_generate", payload)).get("isError")
    assert seen == [
        ("transition", workflows["a"]),
        ("transition", workflows["global"]),
        ("transition", workflows["global"]),
        ("generate", workflows["a"]),
        ("generate", workflows["global"]),
    ]

    own_plan = WorkChangePlan(
        work_item_id=item_a.id,
        version=4,
        status="ready_for_review",
        title="plan stored with the own workflow",
        created_by=world.admin.id,
        workflow_id=workflows["a"],
    )
    db.add(own_plan)
    await db.commit()
    decided = await mcp_call(
        token, "change_plan_decide", {"change_plan_id": own_plan.id, "action": "request_clarification", "reason": "x"}
    )
    assert decided["status"] == "needs_clarification"
