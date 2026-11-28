"""``product_run_list`` lists workflow runs, not chat turns, unless asked."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.models import Session as ChatSession
from app.models.runtime.product_run import ProductRun
from app.models.runtime.workflow_run import WorkflowRun
from app.services.mcp_governed_knowledge import CHAT_TRANSPORT, McpCaller
from app.services.mcp_work_status_tools import mcp_product_run_list
from app.time_utils import utc_now


def _turn(project: Project, user: User, session: ChatSession, *, origin: str, minutes_ago: int) -> ProductRun:
    return ProductRun(workspace_id=project.id, owner_user_id=user.id, session_id=session.id, origin=origin,
                      workspace_source="session_project", state="completed",
                      created_at=utc_now() - timedelta(minutes=minutes_ago))


@pytest.mark.asyncio
async def test_t17_latest_run_is_the_workflow_run_not_the_chat_turn(db: AsyncSession, auth_user: User) -> None:
    project = Project(name=f"run-list-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    chat, other = ChatSession(user_id=auth_user.id, project_id=project.id), ChatSession(
        user_id=auth_user.id, project_id=project.id)
    db.add_all([chat, other])
    await db.flush()
    own = _turn(project, auth_user, chat, origin="chat_turn", minutes_ago=0)
    child = _turn(project, auth_user, other, origin="sub_agent", minutes_ago=1)
    elsewhere = _turn(project, auth_user, other, origin="chat_turn", minutes_ago=5)
    scheduled = _turn(project, auth_user, other, origin="scheduled_task", minutes_ago=20)
    older = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="ticket-delivery",
                        title="CHEF-11", requested_by=auth_user.id, status="completed",
                        created_at=utc_now() - timedelta(hours=2))
    newest = WorkflowRun(project_id=project.id, workflow_kind="phased", workflow_key="ticket-delivery",
                         title="CHEF-12", requested_by=auth_user.id, status="completed",
                         created_at=utc_now() - timedelta(minutes=10))
    db.add_all([own, child, elsewhere, scheduled, older, newest])
    await db.flush()
    caller = McpCaller(user_id=auth_user.id, grant_id=None, scopes=("sessions:read",), bound_project_ids=(project.id,),
                       transport=CHAT_TRANSPORT, chat_session_id=chat.id)

    listed = await mcp_product_run_list(db, caller=caller, user=auth_user, workspace_id=project.id, arguments={})

    assert [run["id"] for run in listed["workflow_runs"]] == [newest.id, older.id]
    assert listed["workflow_runs"][0]["started_by_you"] is True
    assert [run["id"] for run in listed["runs"]] == [scheduled.id]
    everything = await mcp_product_run_list(db, caller=caller, user=auth_user, workspace_id=project.id,
                                            arguments={"include_chat_turns": True})
    assert [run["id"] for run in everything["runs"]] == [own.id, child.id, elsewhere.id, scheduled.id]
