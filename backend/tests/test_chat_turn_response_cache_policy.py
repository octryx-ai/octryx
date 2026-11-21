"""A Chat turn always reaches the model; only unbound callers may use the response cache."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.agent.engine import run_agent
from app.models import Project, User
from app.models import Session as ChatSession
from app.services.llm_cache.dispatch_policy import response_cache_allowed
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

FINAL = {"content": "It is midnight UTC.", "tool_calls": None, "usage": {"prompt_tokens": 7, "completion_tokens": 2}}


def test_policy_excludes_chat_turns_tools_and_tool_results() -> None:
    plain = [{"role": "user", "content": "hi"}]
    assert response_cache_allowed(run_origin=None, tools=None, messages=plain)
    assert not response_cache_allowed(run_origin="chat_turn", tools=None, messages=plain)
    assert not response_cache_allowed(run_origin=None, tools=[{"name": "t"}], messages=plain)
    assert not response_cache_allowed(run_origin=None, tools=None, messages=[*plain, {"role": "tool"}])


@pytest.fixture
def dispatch(monkeypatch):
    """A tool-less turn with a scripted provider; records cache lookups and provider calls."""
    state: dict[str, Any] = {"lookups": 0, "calls": 0}
    original_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = []
        return prepared

    async def lookup(*_args, **_kwargs):
        state["lookups"] += 1
        return None

    def provider_factory(**_kwargs):
        class _Provider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                state["calls"] += 1
                return {**FINAL, "model": model or ""}

            async def close(self):
                return None

        return _Provider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare)
    monkeypatch.setattr(engine_module, "lookup_cached_llm_response", lookup)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return state


async def _session(db) -> ChatSession:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(name=f"cache-policy-{uuid.uuid4().hex[:10]}", config={}, is_active=True)
    db.add(project)
    await db.flush()
    session = ChatSession(
        id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat", status="running", metadata_=dict(UNDECLARED_READ_ONLY_RUN)
    )
    db.add(session)
    await db.commit()
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize(("run_origin", "lookups"), [("chat_turn", 0), (None, 1)], ids=["chat-turn", "unbound"])
async def test_only_unbound_dispatches_consult_the_response_cache(db, dispatch, run_origin, lookups) -> None:
    session = await _session(db)

    events = run_agent(
        session_id=session.id,
        user_message="What time is it?",
        user_id=session.user_id,
        project_id=session.project_id,
        agent_type="chat",
        db=db,
        run_origin=run_origin,
    )
    _ = [event async for event in events]

    assert dispatch["calls"] == 1
    assert dispatch["lookups"] == lookups
