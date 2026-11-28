"""Provider-call probes for direct-agent preparation; only the external model provider is replaced."""

import json
import uuid
from contextlib import asynccontextmanager

import pytest

import app.agent.providers as providers_module
import app.services.control_plane_service as control_plane_module
from app.models import Session as AgentSession
from app.services.session.turn_refusals import TurnRefusal, TurnRefusalState
from app.services.session.turn_request import PreparedTurn, TurnRequest
from app.services.session.turn_start import TURN_PREPARE_LOCK, prepare_turn
from tests.agent_definition_revision_fixtures import admin_user, make_definition

pytestmark = pytest.mark.workflow_proposals
PROMPT = "Synthetic acceptance numbers: 17, 25, 8."


@pytest.fixture
def proposal_calls(monkeypatch):
    calls = []

    class Provider:
        async def chat(self, *, messages, model, temperature, max_tokens):
            calls.append({"lock_held": TURN_PREPARE_LOCK.locked()})
            return {
                "content": json.dumps({"workflow_key": None, "confidence": "low", "reason": "No match."}),
                "usage": {"prompt_tokens": 40, "completion_tokens": 12},
                "model": model,
            }

    async def runtimes(_db, runtime_target_id=None, **_kwargs):
        return [{"provider_name": "fake", "model": "fake-model"}]

    monkeypatch.setattr(control_plane_module, "resolve_control_plane_runtimes", runtimes)
    monkeypatch.setattr(providers_module, "get_provider", lambda **_kwargs: Provider())
    return calls


def session_factory(db):
    @asynccontextmanager
    async def factory():
        yield db

    return factory


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["explicit", "session"])
async def test_direct_agent_does_not_spend_a_workflow_proposal_call(db, proposal_calls, selection):
    owner = await admin_user(db)
    definition = await make_definition(db, owner=owner, steps=0)
    fields = {"agent_id": definition.id}
    if selection == "session":
        session = AgentSession(
            id=str(uuid.uuid4()),
            user_id=owner.id,
            agent_type="chat",
            status="active",
            metadata_={"bound_agent_definition_id": definition.id},
        )
        db.add(session)
        await db.flush()
        fields = {"session_id": session.id}

    result = await prepare_turn(
        TurnRequest(user_id=owner.id, prompt=PROMPT, **fields), session_factory=session_factory(db)
    )

    assert isinstance(result, PreparedTurn), result
    assert result.agent_definition["id"] == definition.id
    assert proposal_calls == [], "A directly selected agent must not pay for automatic workflow selection"


@pytest.mark.asyncio
async def test_missing_agent_is_refused_before_a_provider_call(db, proposal_calls):
    owner = await admin_user(db)
    result = await prepare_turn(
        TurnRequest(user_id=owner.id, prompt=PROMPT, agent_id=str(uuid.uuid4())),
        session_factory=session_factory(db),
    )

    assert isinstance(result, TurnRefusal), result
    assert result.state == TurnRefusalState.AGENT_NOT_FOUND
    assert proposal_calls == [], "Invalid agent selection must not incur a proposal model call"


