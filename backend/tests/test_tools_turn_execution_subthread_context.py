"""Collecting child session context from subthreads."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Message, Session, ToolCall, User
from app.tools.context import ToolContext
from app.tools.sub_agent import GetContextFromSubthreadsTool


@pytest.mark.asyncio
async def test_get_context_from_subthreads_collects_child_session_context(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        metadata_={
            "title": "Parent orchestration",
            "current_sub_agent_group_id": "group-1",
            "sub_agent_group_child_session_ids": ["child-a", "child-b"],
        },
    )
    child_a = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="completed",
        metadata_={"title": "Inspect alpha"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    child_b = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="error",
        metadata_={"title": "Inspect beta"},
        parent_session_id=parent_session.id,
        sub_agent_depth=1,
    )
    db.add_all([parent_session, child_a, child_b])
    db.add_all(
        [
            Message(session_id=child_a.id, role="user", content="Inspect service alpha"),
            Message(session_id=child_a.id, role="assistant", content="Alpha uses report-builder via startup flow."),
            Message(session_id=child_b.id, role="user", content="Inspect service beta"),
            Message(session_id=child_b.id, role="assistant", content="Beta failed because the image was missing."),
        ]
    )
    db.add_all(
        [
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=child_a.id,
                tool_name="search_confluence",
                parameters={"query": "report-builder alpha"},
                result={"status": "ok"},
                status="success",
            ),
            ToolCall(
                id=str(uuid.uuid4()),
                session_id=child_b.id,
                tool_name="list_recent_bitbucket_commits",
                parameters={"days": 7},
                result={"status": "ok"},
                status="success",
            ),
        ]
    )
    await db.commit()

    tool = GetContextFromSubthreadsTool()
    result = await tool.execute(
        {},
        ToolContext(
            user_id=admin.id,
            project_ids=[],
            roles=["admin"],
            session_id=parent_session.id,
            project_config={},
            db=db,
            workspace_root=str(Path.cwd()),
        ),
    )

    assert result["parent_session_id"] == parent_session.id
    assert result["count"] == 2
    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 1
    assert result["summary"]["completed"] == 1
    assert result["summary"]["failed"] == 1
    assert result["summary"]["accepted"] == 1
    assert result["summary"]["rejected"] == 1
    assert "search_confluence" in result["summary"]["tool_names"]
    assert "list_recent_bitbucket_commits" in result["summary"]["tool_names"]
    assert result["merge_contract"]["status"] == "blocked_incomplete"
    assert result["merge_contract"]["requires_review"] is True
    assert result["subthreads"][0]["task"] == "Inspect service alpha"
    assert "Alpha uses report-builder" in result["subthreads"][0]["final_response"]
    assert result["subthreads"][0]["quality"]["accepted"] is True
    assert result["rejected_subthreads"][0]["quality"]["accepted"] is False
    assert "session_not_completed" in result["rejected_subthreads"][0]["quality"]["rejection_reasons"]
    await db.refresh(parent_session)
    assert "current_sub_agent_group_id" not in (parent_session.metadata_ or {})
    assert "sub_agent_group_child_session_ids" not in (parent_session.metadata_ or {})
    assert parent_session.metadata_["subtask_merge_contract"]["status"] == "blocked_incomplete"
