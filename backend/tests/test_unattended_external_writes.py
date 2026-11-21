"""A run no person started writes externally only as a proposal a person approves.

Event-triggered and scheduled runs (an Action a webhook or a poll fired, the Jira watch) read content third parties
wrote and have nobody in the loop. With the empty platform default policy a ``deliver`` run wrote to Jira with
nobody deciding. Now each external write of such a run creates an approval; reads and platform state stay
automatic; only a platform admin can allow a specific tool for unattended runs (not a Workspace).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import User
from app.services.approval.resolution_service import resolve_approval_request
from app.services.tool_approval_gate import enforce_tool_approval
from app.services.tool_approval_policy import platform_default, set_platform_default
from app.services.tool_approval_write_kinds import unattended_external_write
from app.tools.context import ToolContext

WRITE_TOOL = "add_jira_comment"
READ_TOOL = "get_jira_ticket"
SCHEDULED = {"class": "deliver", "enforced": True, "source": "schedule_definition"}
HUMAN_STARTED_RUN = {"class": "deliver", "enforced": True, "source": "flow_definition"}


def _context(run_capability: dict | None, *, user_id: str = "user-1", session_id: str = "s-1", db=None,
             project_config: dict | None = None) -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=["p-1"], roles=["operator"], session_id=session_id,
                       project_config=project_config or {}, db=db, run_capability=run_capability)


def test_only_external_writes_of_unattended_runs_are_proposals() -> None:
    assert unattended_external_write(WRITE_TOOL, _context(SCHEDULED), None) is True
    assert unattended_external_write(READ_TOOL, _context(SCHEDULED), None) is False
    assert unattended_external_write("work_item_note", _context(SCHEDULED), None) is False  # platform state
    assert unattended_external_write(WRITE_TOOL, _context(HUMAN_STARTED_RUN), None) is False
    assert unattended_external_write(WRITE_TOOL, _context(None), None) is False
    # A URL the ticket names carries data out in its query: a person decides that fetch too.
    assert unattended_external_write("web_fetch", _context(SCHEDULED), None) is True
    assert unattended_external_write("web_fetch", _context(HUMAN_STARTED_RUN), None) is False


@pytest.fixture
def restore_platform_default():
    saved = platform_default()
    yield
    set_platform_default(saved)


@pytest.mark.asyncio
async def test_unattended_write_waits_for_a_person_then_runs_once(db, restore_platform_default) -> None:
    set_platform_default({})
    user = (await db.execute(select(User))).scalars().first()
    session = AgentSession(id="unattended-session", user_id=user.id, agent_type="chat", status="active")
    db.add(session)
    await db.flush()
    context = _context(SCHEDULED, user_id=user.id, session_id=session.id, db=db)
    params = {"ticket_id": "BRD-1", "body": "Analysis attached."}

    blocked = await enforce_tool_approval(WRITE_TOOL, params, context)
    assert blocked is not None and blocked["approval_required"] is True
    assert await enforce_tool_approval(READ_TOOL, {"ticket_id": "BRD-1"}, context) is None

    await resolve_approval_request(db, approval_id=blocked["approval_id"], resolved_by=user.id, status="approved")
    assert await enforce_tool_approval(WRITE_TOOL, params, context) is None
    assert await enforce_tool_approval(WRITE_TOOL, params, context) is not None  # one decision, one write


@pytest.mark.asyncio
async def test_only_the_platform_default_can_allow_a_tool_for_unattended_runs(db, restore_platform_default) -> None:
    workspace_allows = {"approval_policy": {"unattended_allowed_tools": [WRITE_TOOL]}}
    set_platform_default({})
    blocked = await enforce_tool_approval(WRITE_TOOL, {"body": "x"},
                                          _context(SCHEDULED, db=db, project_config=workspace_allows))
    assert blocked is not None  # a Workspace cannot waive it

    set_platform_default({"unattended_allowed_tools": [WRITE_TOOL]})
    assert await enforce_tool_approval(WRITE_TOOL, {"body": "x"}, _context(SCHEDULED, db=db)) is None
    assert await enforce_tool_approval("create_jira_ticket", {"summary": "x"}, _context(SCHEDULED, db=db)) is not None
