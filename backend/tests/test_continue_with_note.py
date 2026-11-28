"""A paused phase can be run again with a note for the agent: a person who sees problems in the screenshots can
say them when running the phase again."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.actions import NOTE_INPUT, available_actions, perform_action
from app.services.workflow_runs.limits import pause_run
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.states import PAUSE_RUNTIME_FAILED
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_run_the_phase_again_carries_the_note_as_a_product_owner_answer(db):
    workspace_id = await seed_workspace(db)
    admin = await admin_user(db)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=await new_chat_session(db, admin, workspace_id))
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": "The agent ended its turn without finishing this phase.", "code": "phase_not_finished",
        "resume": {"kind": "restart", "node_id": run.current_node_id}})
    await db.commit()
    actions = {item["key"]: item for item in await available_actions(db, run, access="write", user=admin)}
    assert actions["continue"]["input"] == NOTE_INPUT

    note = "The screenshot shows raw keys like search.filter.vegan and no dish cards: fix both."
    await perform_action(db, run, user=admin, body={"action": "continue", "reason": note})
    await db.refresh(run)
    assert run.status == "running"
    assert [item["text"] for item in run.context["po_answers"]] == [note]
