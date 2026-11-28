"""an alert-started run carries the alert; ``get_run_alert`` reads it for the session's own run only."""

from __future__ import annotations

import uuid

import pytest

from app.services.workflow_runs.records import new_chat_session, start_run
from app.tools.context import ToolContext
from app.tools.run_alert import MAX_PAYLOAD_BYTES, NO_ALERT, GetRunAlert, bounded_payload
from tests.phased_workflow_fixtures import admin_user, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")




def _context(db, session_id: str | None, user_id: str = "u") -> ToolContext:
    return ToolContext(user_id=user_id, project_ids=[], roles=[], session_id=session_id, project_config={}, db=db)






@pytest.mark.asyncio
async def test_get_run_alert_refuses_without_a_run_or_an_alert(db):
    tool = GetRunAlert()
    assert await tool.execute({}, _context(None, "s")) == {"error": NO_ALERT}
    assert await tool.execute({}, _context(db, None)) == {"error": NO_ALERT}
    assert await tool.execute({}, _context(db, str(uuid.uuid4()))) == {"error": NO_ALERT}, "a session with no run"

    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key="incident-analysis", project_id=workspace_id, session=session)
    await db.commit()
    assert run.context.get("alert") is None
    assert await tool.execute({"run_id": run.id}, _context(db, session.id, admin.id)) == {"error": NO_ALERT}




def test_the_payload_is_bounded():
    small = {"a": 1}
    assert bounded_payload(small) is small
    big = {"text": "x" * (MAX_PAYLOAD_BYTES + 1)}
    bounded = bounded_payload(big)
    assert bounded["truncated"] is True and len(bounded["preview"]) == 4000


