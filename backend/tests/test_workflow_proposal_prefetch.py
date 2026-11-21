"""The workflow proposal resolves before the process-global chat preparation lock.

A slow proposal provider must not delay other users' turns: turn preparation
(``services/session/turn_start.prepare_turn``, both entry paths) resolves the proposal in its own
session before ``TURN_PREPARE_LOCK`` and hands it in, keyed by the Workspace and the prompt hash.
Under the lock no proposal model call is ever made.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

import app.agent.providers as providers_module
import app.services.control_plane_service as control_plane_module
import app.services.session.turn_prepare as turn_prepare_module
import app.services.workflow_routing.proposal_prefetch as prefetch_module
from app.models import Session as AgentSession
from app.models import User
from app.services.session.turn_request import PreparedTurn, TurnRequest
from app.services.session.turn_start import TURN_PREPARE_LOCK, prepare_turn
from app.services.workflow_routing.explicit_selection import resolve_workflow_selection_for_turn
from app.services.workflow_routing.proposal_prefetch import (
    PrecomputedWorkflowProposal,
    prefetch_workflow_proposal,
    proposal_prompt_hash,
)
from app.services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

PHASED_WORKFLOW = "incident-analysis"
MESSAGE = "Analyse the payment service outage from this morning."

pytestmark = pytest.mark.workflow_proposals


class _FakeProvider:
    """Answers the proposal call and records whether the preparation lock was held."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.lock_held: list[bool] = []

    def __call__(self, **_kwargs):
        return self

    async def chat(self, *, messages, model, temperature, max_tokens):
        self.lock_held.append(TURN_PREPARE_LOCK.locked())
        return {"content": self.content, "usage": {"prompt_tokens": 40, "completion_tokens": 12}, "model": model}


@pytest.fixture
def provider(monkeypatch) -> _FakeProvider:
    fake = _FakeProvider(json.dumps({"workflow_key": PHASED_WORKFLOW, "confidence": "high", "requested": True, "reason": "An outage."}))

    async def fake_runtimes(_db, runtime_target_id=None, **_kwargs):
        return [{"provider_name": "fake", "model": "fake-model"}]

    monkeypatch.setattr(control_plane_module, "resolve_control_plane_runtimes", fake_runtimes)
    monkeypatch.setattr(providers_module, "get_provider", fake)
    return fake


def _factory(db):
    @asynccontextmanager
    async def session_factory():
        yield db

    return session_factory


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


@pytest.mark.asyncio
async def test_a_slow_proposal_does_not_hold_the_preparation_lock(db, monkeypatch):
    admin = await _admin(db)
    entered, release = asyncio.Event(), asyncio.Event()
    prepared: list[dict] = []

    async def slow_proposal(_db, *, user_message, project_id):
        entered.set()
        await release.wait()
        return {"status": "unmatched", "workflow_proposal": {"reason_code": "timeout"}}

    async def fake_prepare_turn_in_session(_db, **kwargs):
        prepared.append(kwargs)
        return PreparedTurn(f"session-{len(prepared)}", "message", "prompt", None, "chat", None, "light", None)

    monkeypatch.setattr(prefetch_module, "resolve_workflow_proposal_for_turn", slow_proposal)
    monkeypatch.setattr(turn_prepare_module, "prepare_turn_in_session", fake_prepare_turn_in_session)
    factory = _factory(db)

    slow_turn = asyncio.create_task(prepare_turn(TurnRequest(user_id=admin.id, prompt=MESSAGE), session_factory=factory))
    await entered.wait()
    assert not TURN_PREPARE_LOCK.locked()
    # Another turn prepares completely while the first turn's proposal is still pending.
    other = await prepare_turn(
        TurnRequest(user_id=admin.id, prompt="Other turn", workflow_key=PHASED_WORKFLOW), session_factory=factory
    )
    assert other.session_id == "session-1" and not slow_turn.done()

    release.set()
    assert (await slow_turn).session_id == "session-2"
    precomputed = prepared[1]["precomputed_proposal"]
    assert precomputed.resolution["workflow_proposal"]["reason_code"] == "timeout"
    assert prepared[0]["precomputed_proposal"] is None


@pytest.mark.asyncio
async def test_the_precomputed_proposal_is_used_with_one_model_call_outside_the_lock(db, provider):
    admin = await _admin(db)

    session_id = (
        await prepare_turn(
            TurnRequest(user_id=admin.id, prompt=f"  {MESSAGE}  ", agent_type="diagnosis"), session_factory=_factory(db)
        )
    ).session_id

    assert provider.lock_held == [False]
    session = await db.get(AgentSession, session_id)
    resolution = session.metadata_[ROUTING_RESOLUTION_KEY]
    proposal = resolution["workflow_proposal"]
    assert (resolution["source"], resolution["status"]) == ("workflow_proposal", "needs_confirmation")
    assert (proposal["reason_code"], proposal["workflow_key"]) == ("workflow_run_required", PHASED_WORKFLOW)
    assert proposal["dispatch"]["calls"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "prompt", "resolved"),
    [("other-project", MESSAGE, True), ("", "A different prompt", True), ("", MESSAGE, False)],
)
async def test_a_key_mismatch_is_scope_changed_without_a_model_call(db, provider, scope, prompt, resolved):
    applied = {"status": "matched", "workflow_proposal": {"status": "applied"}}
    precomputed = PrecomputedWorkflowProposal(
        project_id=scope, prompt_hash=proposal_prompt_hash(prompt), resolution=applied if resolved else None
    )

    resolution = await resolve_workflow_selection_for_turn(
        db, user_message=MESSAGE, project_id=None, precomputed_proposal=precomputed
    )

    assert provider.lock_held == []
    assert resolution["workflow_proposal"]["status"] == "none"
    assert resolution["workflow_proposal"]["reason_code"] == "proposal_scope_changed"
    assert resolution["status"] == "unmatched" and resolution["workflow_id"] is None


@pytest.mark.asyncio
async def test_an_explicit_workflow_key_makes_no_proposal_call(db, provider):
    admin = await _admin(db)
    factory = _factory(db)

    for workflow_key in (PHASED_WORKFLOW, "none"):
        assert (
            await prefetch_workflow_proposal(factory, user_id=admin.id, prompt=MESSAGE, workflow_key=workflow_key)
            is None
        )
    session_id = (
        await prepare_turn(
            TurnRequest(user_id=admin.id, prompt=MESSAGE, workflow_key=PHASED_WORKFLOW), session_factory=factory
        )
    ).session_id

    assert provider.lock_held == []
    resolution = (await db.get(AgentSession, session_id)).metadata_[ROUTING_RESOLUTION_KEY]
    # The explicit phased key holds its start card without asking the proposal model.
    proposal = resolution["workflow_proposal"]
    assert (proposal["reason_code"], proposal["workflow_key"]) == ("explicit_phased_selection", PHASED_WORKFLOW)
    assert proposal["dispatch"] is None
