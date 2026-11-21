"""The agent is admitted before the automatic workflow proposal.

Real turn preparation, routing and agent selection; only the proposal provider is replaced (the
fixtures of the root judge module). A directly chosen, admitted agent (explicit, exact mention,
the session's bound agent) skips the proposal as ``direct_agent_selected``; a refused agent makes
no call; the Workspace default and an agent-type override keep the proposal; an
explicit workflow keeps its own selection. Preparation keeps a skip only for the same agent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Session as AgentSession
from app.models import SessionCollaborator, UsageEvent
from app.services.session.turn_prepare import prepare_turn_in_session
from app.services.session.turn_refusals import TurnRefusal, TurnRefusalState, TurnRefusedError
from app.services.session.turn_request import SESSION_SCOPE_EXISTING, PreparedTurn, TurnRequest
from app.services.session.turn_start import prepare_turn
from app.services.workflow_routing.proposal_prefetch import prefetch_workflow_proposal
from app.services.workflow_routing.proposal_states import WORKFLOW_PROPOSAL_KEY
from app.services.workflow_routing.proposal_usage import record_workflow_proposal_usage
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY
from tests import test_direct_agent_proposal_cost_judge as judge
from tests.agent_definition_revision_fixtures import admin_user, make_definition, make_member, make_project, make_user
from tests.turn_agent_selection_support import _workspace

pytestmark = pytest.mark.workflow_proposals
# The root judge module's provider stand-in and in-test session factory.
PROMPT = judge.PROMPT
proposal_calls = judge.proposal_calls
session_factory = judge.session_factory


def _reason(session: AgentSession) -> str:
    return session.metadata_[ROUTING_RESOLUTION_KEY][WORKFLOW_PROPOSAL_KEY]["reason_code"]


async def _prepare(db, **fields) -> PreparedTurn | TurnRefusal:
    owner = fields.pop("user_id", None) or (await admin_user(db)).id
    return await prepare_turn(TurnRequest(user_id=owner, prompt=PROMPT, **fields), session_factory=session_factory(db))


async def _bound_session(db, *, owner, definition_id: str, project_id: str | None = None) -> AgentSession:
    session = AgentSession(
        id=str(uuid.uuid4()), user_id=owner.id, project_id=project_id, agent_type="chat", status="active",
        metadata_={"bound_agent_definition_id": definition_id},
    )
    db.add(session)
    await db.flush()
    return session


@pytest.mark.asyncio
async def test_a_skip_records_its_closed_reason_and_no_usage_while_a_proposal_records_one_event(db, proposal_calls):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)

    direct = await _prepare(db, agent_id=definition.id)
    plain = await _prepare(db)

    assert len(proposal_calls) == 1, "only the turn without an agent asked for a proposal"
    usage = []
    for prepared in (direct, plain):
        session = await db.get(AgentSession, prepared.session_id)
        metadata = dict(session.metadata_)
        usage.append(await record_workflow_proposal_usage(db, session_metadata=metadata, session_id=session.id,
                                                          user_id=owner.id))
        if prepared is direct:
            assert _reason(session) == "direct_agent_selected"
            assert session.metadata_[ROUTING_RESOLUTION_KEY][WORKFLOW_PROPOSAL_KEY]["dispatch"] is None
    assert usage[0] is None and usage[1] is not None, "a skipped proposal leaves no usage event"
    await db.flush()
    owners = (await db.execute(select(UsageEvent.session_id).where(UsageEvent.dispatch_owner == "workflow_proposal"))).scalars().all()
    assert owners == [plain.session_id]


@pytest.mark.asyncio
async def test_an_exact_mention_is_a_direct_choice(db, proposal_calls):
    ws = await _workspace(db, default_agent=False)
    mentioned = ws.agents["mention"]
    result = await prepare_turn(
        TurnRequest(user_id=ws.admin.id, prompt=f"@{mentioned.name} {PROMPT}", project_id=ws.project.id),
        session_factory=session_factory(db),
    )
    assert isinstance(result, PreparedTurn), result
    assert result.agent_definition["id"] == mentioned.id
    assert proposal_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["inactive", "foreign"])
async def test_a_refused_agent_makes_no_proposal_call(db, proposal_calls, case):
    owner = await admin_user(db)
    # A3: a Workspace agent is hidden from users outside that Workspace.
    definition = await make_definition(db, owner=owner, steps=0, project_id=(await make_project(db)).id)
    caller = owner
    if case == "inactive":
        definition.is_active = False
        await db.flush()
    else:
        caller = await make_user(db, label="foreign-proposal")
        await make_member(db, caller, await make_project(db), "member")

    result = await _prepare(db, user_id=caller.id, agent_id=definition.id)

    assert isinstance(result, TurnRefusal), result
    expected = TurnRefusalState.AGENT_DEFINITION_REFUSED if case == "inactive" else TurnRefusalState.AGENT_NOT_FOUND
    assert result.state == expected
    assert proposal_calls == []


@pytest.mark.asyncio
async def test_a_workspace_default_agent_keeps_the_proposal(db, proposal_calls):
    ws = await _workspace(db, default_agent=True)
    result = await prepare_turn(
        TurnRequest(
            user_id=ws.admin.id, prompt=PROMPT, project_id=ws.project.id,
        ),
        session_factory=session_factory(db),
    )
    assert isinstance(result, PreparedTurn), result
    assert result.agent_definition["id"] == ws.agents["default"].id
    assert len(proposal_calls) == 1


@pytest.mark.asyncio
async def test_an_agent_type_override_does_not_skip_for_the_stale_bound_agent(db, proposal_calls):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)
    session = await _bound_session(db, owner=owner, definition_id=definition.id)

    result = await _prepare(db, session_id=session.id, agent_type="chat", agent_type_explicit=True)

    assert isinstance(result, PreparedTurn), result
    assert result.agent_definition["builtinKey"] == "assistant"  # the platform default
    assert len(proposal_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_key", ["none", "unknown-workflow-1141"])
async def test_an_explicit_workflow_keeps_its_own_selection_with_an_agent(db, proposal_calls, workflow_key):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)

    result = await _prepare(db, agent_id=definition.id, workflow_key=workflow_key)

    assert proposal_calls == []
    if isinstance(result, PreparedTurn):
        session = await db.get(AgentSession, result.session_id)
        resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
        assert (resolution.get(WORKFLOW_PROPOSAL_KEY) or {}).get("reason_code") != "direct_agent_selected"


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "expected"), [("contributor", "skip"), ("observer", TurnRefusalState.SESSION_ACCESS_DENIED)])
async def test_a_shared_session_is_admitted_under_the_writable_scope(db, proposal_calls, role, expected):
    owner = await admin_user(db)
    project = await make_project(db)
    definition = await make_definition(db, owner=owner, project_id=project.id, steps=0)
    session = await _bound_session(db, owner=owner, definition_id=definition.id, project_id=project.id)
    writer = await make_user(db, label=f"shared-{role}")
    await make_member(db, owner, project, "owner")
    await make_member(db, writer, project, "member")
    db.add(SessionCollaborator(session_id=session.id, user_id=writer.id, role=role, invited_by=owner.id))
    await db.flush()

    result = await _prepare(db, user_id=writer.id, session_id=session.id, session_scope=SESSION_SCOPE_EXISTING)

    assert proposal_calls == []
    if expected == "skip":
        assert isinstance(result, PreparedTurn), result
        assert result.agent_definition["id"] == definition.id, "the session owner's agent, as in preparation"
    else:
        assert isinstance(result, TurnRefusal) and result.state == expected


async def _prefetched_for_bound_session(db):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)
    session = await _bound_session(db, owner=owner, definition_id=definition.id)
    precomputed = await prefetch_workflow_proposal(
        session_factory(db), user_id=owner.id, prompt=PROMPT, session_id=session.id
    )
    assert precomputed.direct_agent is not None and precomputed.direct_agent.agent_id == definition.id
    return owner, definition, session, precomputed


@pytest.mark.asyncio
async def test_a_binding_removed_after_the_skip_is_recorded_as_scope_changed_without_a_call(db, proposal_calls):
    owner, _definition, session, precomputed = await _prefetched_for_bound_session(db)
    session.metadata_ = {"bound_agent_definition_id": None}
    await db.flush()

    prepared = await prepare_turn_in_session(
        db, user=owner, request=TurnRequest(user_id=owner.id, prompt=PROMPT, session_id=session.id),
        precomputed_proposal=precomputed,
    )

    assert prepared.agent_definition["builtinKey"] == "assistant"  # the platform default
    assert _reason(await db.get(AgentSession, prepared.session_id)) == "proposal_scope_changed"
    assert proposal_calls == []


@pytest.mark.asyncio
async def test_an_agent_deactivated_after_the_skip_is_refused_under_the_lock(db, proposal_calls):
    owner, definition, session, precomputed = await _prefetched_for_bound_session(db)
    definition.is_active = False
    await db.flush()

    with pytest.raises(TurnRefusedError) as refused:
        await prepare_turn_in_session(
            db, user=owner, request=TurnRequest(user_id=owner.id, prompt=PROMPT, session_id=session.id),
            precomputed_proposal=precomputed,
        )
    assert refused.value.refusal.state == TurnRefusalState.AGENT_DEFINITION_REFUSED
    assert proposal_calls == []
