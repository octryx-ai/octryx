"""The proposal call writes exactly one usage event, and the proposal policy is validated."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.context.run_context_routing import resolve_turn_routing_profile
from app.models import Session, UsageEvent, User
from app.services.workflow_routing.explicit_selection import resolve_workflow_selection_for_turn
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests.workflow_proposal_support import MESSAGE, _answer, proposal_model  # noqa: F401

pytestmark = pytest.mark.workflow_proposals

PHASED_WORKFLOW = "incident-analysis"


@pytest.mark.asyncio
async def test_the_proposal_call_writes_exactly_one_usage_event(db, proposal_model):  # noqa: F811
    proposal_model(_answer(PHASED_WORKFLOW))
    resolution = await resolve_workflow_selection_for_turn(db, user_message=MESSAGE)
    usage_id = resolution["workflow_proposal"]["dispatch"]["usage_id"]
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=user.id, agent_type="diagnosis", status="running", metadata_={})
    db.add(session)
    await db.flush()
    metadata = {ROUTING_RESOLUTION_KEY: resolution}

    # Run preparation owns the session; a repeated preparation of the same turn (resume) and a
    # copy of the metadata without the marker both find the event and write nothing.
    for session_metadata in (metadata, metadata, {ROUTING_RESOLUTION_KEY: resolution}):
        await resolve_turn_routing_profile(
            db=db,
            session_metadata=session_metadata,
            user_message=MESSAGE,
            agent_type="diagnosis",
            project_id=None,
            agent_definition=None,
            runtime_target_id=None,
            session_id=session.id,
            user_id=user.id,
        )
    await db.flush()

    rows = (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    assert len(rows) == 1
    event = rows[0]
    assert event.request_id == f"workflow_proposal:{usage_id}"
    assert event.dispatch_owner == "workflow_proposal"
    assert (event.provider, event.model, event.tokens_in, event.tokens_out) == ("fake", "fake-model", 40, 12)
    assert event.user_id == user.id and event.cost_status
    recorded = metadata[ROUTING_RESOLUTION_KEY]["workflow_proposal"]["dispatch"]
    assert recorded["usage_event_id"] == event.id


def test_the_proposal_policy_is_validated():
    from app.services.workflow_routing.proposal_policy import (
        WorkflowProposalPolicyError,
        normalize_workflow_proposal_policy,
        workflow_proposals_enabled_in,
    )

    assert normalize_workflow_proposal_policy({"enabled": None}) == {}
    assert normalize_workflow_proposal_policy({"enabled": False}) == {"enabled": False}
    with pytest.raises(WorkflowProposalPolicyError):
        normalize_workflow_proposal_policy({"enabled": "no"})
    # Only an explicit False switches proposals off; the default is on.
    assert workflow_proposals_enabled_in({}) is True
    assert workflow_proposals_enabled_in({"workflow_proposal_policy": {"enabled": False}}) is False
