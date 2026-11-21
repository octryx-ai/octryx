"""Work › Runs: ``GET /workflow-runs?view=work`` adds per run the step with
its place among the phases, the pause facts, the pull request and the model cost (one query for all rows). Without
``view`` the list stays as it was."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import User, WorkflowRunSession
from app.models.runtime.audit import UsageEvent
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


async def test_the_work_view_adds_step_cost_and_pull_request(client, db):
    workspace_id = await seed_workspace(db)
    person = await db.get(User, await seed_member(db, workspace_id=workspace_id, role="member"))
    key = await publish_phased(db, DEFINITION)
    run = await start_run(db, user=person, workflow_key=key, project_id=workspace_id,
                          session=await new_chat_session(db, person, workspace_id))
    run.pull_request = {"provider": "github", "id": 1440, "url": "https://example.test/pr/1440", "state": "open"}
    session_id = (await db.execute(select(WorkflowRunSession.session_id).where(
        WorkflowRunSession.run_id == run.id))).scalars().first()
    assert session_id
    for cost in (Decimal("0.5"), Decimal("0.25")):
        db.add(UsageEvent(session_id=session_id, user_id=person.id, provider="p", model="m", cost=cost))
    await db.commit()

    plain = await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}", headers=bearer(person.id))
    assert plain.status_code == 200, plain.text
    assert "cost" not in plain.json()["runs"][0]
    # The workflow's own title, not one derived from its key.
    assert plain.json()["runs"][0]["workflow_title"] == "Evidence run"

    answer = await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}&view=work", headers=bearer(person.id))
    assert answer.status_code == 200, answer.text
    [row] = answer.json()["runs"]
    assert row["cost"] == 0.75
    assert row["step"]["title"] == "Go on?" and row["step"]["kind"] == "user_confirmation"
    assert row["step"]["index"] is None
    assert row["pull_request"] == {"id": 1440, "url": "https://example.test/pr/1440", "state": "open"}
    assert row["pause"] is None
    assert row["work_item"] is None

    # Bitbucket Server answers without a link: the pull request still shows, by its id.
    run.pull_request = {"provider": "bitbucket", "id": 41, "url": "", "state": "open"}
    await db.commit()
    answer = await client.get(f"/api/v1/workflow-runs?project_id={workspace_id}&view=work", headers=bearer(person.id))
    assert answer.json()["runs"][0]["pull_request"] == {"id": 41, "url": "", "state": "open"}


def test_the_task_list_marks_an_item_done_only_when_its_proof_test_is_in_the_change():
    from types import SimpleNamespace

    from app.services.workflow_runs.run_card_parts import task_list_view

    answer = ("Ready.\nTask list:\nT1. Count per client | proof: tests/test_router.py::test_counts_per_client\n"
              "T2. Retry-After header | proof: tests/test_router.py::test_retry_after\n")
    unknown = SimpleNamespace(context={"answers": {"readiness": answer}})
    assert [(item["id"], item["done"]) for item in task_list_view(unknown)] == [("T1", None), ("T2", None)]
    patch = ("diff --git a/tests/test_router.py b/tests/test_router.py\n+++ b/tests/test_router.py\n"
             "+def test_counts_per_client():\n+    assert True\n")
    changed = SimpleNamespace(context={"answers": {"readiness": answer}, "device_change": {"patch": patch}})
    view = task_list_view(changed)
    assert [(item["id"], item["done"]) for item in view] == [("T1", True), ("T2", False)]
    assert view[0]["proof"] == "tests/test_router.py::test_counts_per_client"
    assert task_list_view(SimpleNamespace(context={})) == []
