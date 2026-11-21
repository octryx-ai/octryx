import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Session, ToolCall, TurnTrace, User
from app.services.session.artifact_visibility import load_user_turn_trace, resolve_user_diagram_artifact


@pytest.mark.asyncio
async def test_resolve_user_diagram_artifact_loads_artifact_tool_call_payload(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        tool_name="create_diagram",
        status="success",
        result={
            "preview": {
                "compact_result": {
                    "diagram_id": "diagram-1",
                    "diagram_xml": "<mxfile />",
                    "title": "Topology",
                }
            }
        },
    )
    db.add_all([session, tool_call])
    await db.flush()

    payload = await resolve_user_diagram_artifact(db, user_id=admin.id, path=f"artifact://{tool_call.id}")

    assert payload["diagram_id"] == "diagram-1"
    assert payload["diagram_xml"] == "<mxfile />"
    assert payload["title"] == "Topology"


@pytest.mark.asyncio
async def test_resolve_user_diagram_artifact_searches_owned_diagram_id(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        tool_name="edit_diagram",
        status="success",
        result={"diagram_id": "diagram-2", "diagram_xml": "<mxfile>two</mxfile>", "title": "Edited"},
    )
    db.add_all([session, tool_call])
    await db.flush()

    payload = await resolve_user_diagram_artifact(db, user_id=admin.id, path="diagram://diagram-2")

    assert payload["diagram_xml"] == "<mxfile>two</mxfile>"


@pytest.mark.asyncio
async def test_resolve_user_diagram_artifact_hides_other_users_tool_calls(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        tool_name="create_diagram",
        status="success",
        result={"diagram_id": "diagram-private", "diagram_xml": "<mxfile />"},
    )
    db.add_all([session, tool_call])
    await db.flush()

    with pytest.raises(HTTPException) as exc_info:
        await resolve_user_diagram_artifact(db, user_id=str(uuid.uuid4()), path=f"artifact://{tool_call.id}")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Diagram artifact not found"


@pytest.mark.asyncio
async def test_load_user_turn_trace_returns_only_owned_trace(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, agent_type="diagnosis", status="active")
    trace = TurnTrace(
        id=str(uuid.uuid4()),
        session_id=session.id,
        provider="bedrock",
        model="anthropic.claude",
        raw_output={"content": "done"},
    )
    db.add_all([session, trace])
    await db.flush()

    assert await load_user_turn_trace(db, user_id=admin.id, trace_id=trace.id) == trace
    assert await load_user_turn_trace(db, user_id=str(uuid.uuid4()), trace_id=trace.id) is None
