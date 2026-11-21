"""``resume_in_new_session`` is offered in ``run.actions``; posting it to ``/actions`` continues the run in a new
chat like ``POST /{run_id}/sessions`` (the API must not refuse its own offer as ``unknown_action``)."""

from __future__ import annotations

import pytest

from app.models import User
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.phased_workflow_fixtures import publish_phased
from tests.policy_engine_support import bearer

pytestmark = pytest.mark.asyncio

DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "r0", "source_node_id": "go", "target_node_id": "done", "when": "confirmed"}],
}


async def test_the_offered_resume_action_opens_a_new_chat_for_the_requester_only(client, db):
    workspace_id = await seed_workspace(db)
    requester = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member"))
    other = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member"))
    first = await new_chat_session(db, requester, workspace_id)
    run = await start_run(db, user=requester, workflow_key=await publish_phased(db, DEFINITION),
                          project_id=workspace_id, session=first)
    await db.commit()

    view = await client.get(f"/api/v1/workflow-runs/{run.id}", headers=bearer(requester.id))
    assert "resume_in_new_session" in {action["key"] for action in view.json()["run"]["actions"]}

    answer = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json={"action": "resume_in_new_session"},
                               headers=bearer(requester.id))
    assert answer.status_code == 200, answer.text
    assert answer.json()["session_id"] and answer.json()["session_id"] != first.id

    refused = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", json={"action": "resume_in_new_session"},
                                headers=bearer(other.id))
    assert refused.status_code in (403, 404), refused.text
