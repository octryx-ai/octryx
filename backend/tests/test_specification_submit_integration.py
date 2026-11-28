"""The actual shared chat-tool handler preserves trusted read provenance before recording S3.1 outputs."""
from __future__ import annotations

import copy

import pytest
from sqlalchemy import func, select

from app.models import FlowDefinition, WorkflowRunEvent
from app.services.workflow_runs.specification.lineage import resolve_spec_snapshot
from app.tools.context import ToolContext
from app.tools.specification_outputs import SubmitResearchBriefTool
from tests.phased_workflow_fixtures import publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.specification_definition_support import specification_definition
from tests.specification_producer_support import producer

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "no_history", "wrong_request"])
async def test_chat_submit_canonicalizes_actual_context_and_never_records_unproved_reads(db, fault):
    run, actor, session, _, _, call, kwargs, brief = await producer(db, complete=False)
    key = await publish_phased(db, specification_definition())
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    run.flow_definition_version_id = flow.current_version_id
    run.status, run.waiting_kind = "running", None
    await db.flush()
    before = copy.deepcopy((run.context, run.node_state, run.loop_counters))
    events = await db.scalar(select(func.count()).select_from(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))
    context = ToolContext(user_id=actor.id, project_ids=[run.project_id], roles=[], session_id=session.id,
        project_config={}, db=db, request_id="other-request" if fault == "wrong_request" else kwargs["request_id"],
        turn_tool_history=[] if fault == "no_history" else kwargs["tool_history"])
    result = await SubmitResearchBriefTool().execute(brief, context)
    if fault:
        assert result["status"] == "refused" and result["error"] == "needs_configuration", result
        assert (run.context, run.node_state, run.loop_counters) == before
        assert await db.scalar(select(func.count()).select_from(WorkflowRunEvent).where(
            WorkflowRunEvent.run_id == run.id)) == events
    else:
        assert result["status"] == "recorded", result
        snapshot = await resolve_spec_snapshot(db, run, principal=actor, purpose="preview", kind="research_brief")
        assert snapshot["evidence"][0]["call_id"] == call.id
        assert snapshot["envelope"]["hash"] == result["hash"]
        proofs = (await db.execute(select(WorkflowRunEvent).where(
            WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "specification_read_provenance"))).scalars().all()
        assert len(proofs) == 1 and proofs[0].detail["call_ids"] == [call.id]
