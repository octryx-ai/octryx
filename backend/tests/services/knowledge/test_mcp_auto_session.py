from __future__ import annotations

from sqlalchemy import select

from app.models import Session, ToolCall, User
from app.services.knowledge_trust import layer_rank, promoted_layer_on_review_approval
from app.services.mcp_auto_session import record_mcp_tool_activity


async def test_auto_session_created_once_per_grant_and_day(db):
    user = User(username="auto-mcp-user", email="auto-mcp@example.test", password_hash="x")
    db.add(user)
    await db.flush()
    sid1 = await record_mcp_tool_activity(
        db, user=user, grant_id="grant-1", client_name="opencode 1.0",
        tool_name="knowledge_search", arguments={"query": "x"},
    )
    sid2 = await record_mcp_tool_activity(
        db, user=user, grant_id="grant-1", client_name="opencode 1.0",
        tool_name="work_item_find", arguments={"work_item": "OCX-1"},
    )
    assert sid1 == sid2  # same grant + day -> one session
    other = await record_mcp_tool_activity(
        db, user=user, grant_id="grant-2", client_name="codex 0.1",
        tool_name="task_list", arguments={},
    )
    assert other != sid1  # different grant -> own session
    session = await db.get(Session, sid1)
    assert session.agent_type == "external_agent"
    assert session.metadata_["mcp_client"] == "opencode 1.0"
    calls = (await db.execute(select(ToolCall).where(ToolCall.session_id == sid1))).scalars().all()
    assert {call.tool_name for call in calls} == {"knowledge_search", "work_item_find"}


def test_trust_model_v1_rules():
    assert layer_rank("gold") < layer_rank("silver") < layer_rank("bronze")
    assert layer_rank(None) == layer_rank("bronze")
    assert promoted_layer_on_review_approval("bronze", "approved") == "silver"
    assert promoted_layer_on_review_approval("silver", "approved") is None
    assert promoted_layer_on_review_approval("bronze", "rejected") is None


async def test_session_ingest_upserts_by_client_session_id(db):
    from app.models import Project, UsageEvent
    from app.services.mcp_external_session import mcp_session_ingest

    user = User(username="ingest-upsert", email="ingest-upsert@example.test", password_hash="x")
    db.add(user)
    project = Project(name="ingest-upsert-proj")
    db.add(project)
    await db.flush()
    from sqlalchemy import text
    await db.execute(
        text("INSERT INTO user_projects (user_id, project_id) VALUES (:u, :p)"),
        {"u": user.id, "p": project.id},
    )
    await db.flush()

    args = {
        "project_id": project.id,
        "summary": "first",
        "usage": [{"model": "claude-fable-5", "input_tokens": 100, "output_tokens": 10}],
        "client_session_id": "cli-abc",
    }
    first = await mcp_session_ingest(db, user=user, grant_id="g1", arguments=args)
    second = await mcp_session_ingest(
        db, user=user, grant_id="g1",
        arguments={**args, "summary": "second", "usage": [
            {"model": "claude-fable-5", "input_tokens": 200, "output_tokens": 20}
        ]},
    )
    assert first["external_session_id"] == second["external_session_id"]
    session = await db.get(Session, first["external_session_id"])
    assert session.metadata_["summary"] == "second"
    events = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    assert len(events) == 1 and events[0].tokens_in == 200
