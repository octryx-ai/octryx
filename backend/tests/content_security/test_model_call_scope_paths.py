"""Each independent dispatch path supplies its Workspace to the provider wrapper (B-01, captured upstream).

Every path runs its real factory and dispatch site against a captured driver (``model_call_driver_support``; the
real ``openai_compatible`` driver class under the provider wrapper, a fake HTTP upstream). The Workspace stores a
stricter action than the shipped default: internal IPs ``mask`` (shipped: ``report``, the plain address is sent).
The address must not reach the upstream: the stored action applied, so the path named its Workspace. A control
shows the shipped default would have sent it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import Project, WorkspaceContentHandling
from app.services.content_security.model_call_scope import model_call_scope, session_call
from tests.content_security.model_call_driver_support import DRIVERS, Harness, Reply

IP = "10.20.30.40"
PROMPT = f"the build host is {IP}"
ANSWER = '{"answer": "ok", "memories": [], "summary": "ok"}'


async def _workspace(db) -> str:
    """A Workspace whose stored action for internal IPs is ``mask`` (the shipped default reports them)."""
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    db.add(WorkspaceContentHandling(workspace_id=project.id, kind="internal_ip", action="mask"))
    await db.commit()
    return project.id


def _captured(monkeypatch, reply: str = ANSWER) -> tuple[Harness, dict[str, Any]]:
    """Every provider the paths build is the captured driver; the runtime they resolve names it."""
    harness = DRIVERS["openai_compatible"](monkeypatch, Reply(reply))
    monkeypatch.setattr("app.agent.providers.get_provider", lambda **_kwargs: harness.driver)
    runtime = {"provider_name": "direct", "driver": "openai_compatible", "model": harness.model,
               "use_case_tags": ["memory", "extract", "workflow_proposal"]}

    async def runtimes(_db, **_kwargs):
        return [dict(runtime)]

    monkeypatch.setattr("app.services.control_plane_service.resolve_control_plane_runtimes", runtimes)
    return harness, runtime


def _stored_action_applied(harness: Harness) -> None:
    sent = harness.sent()
    assert sent, "the path dispatched"
    assert all(IP not in body for body in sent), "the Workspace's stored mask applied before the upstream"


async def test_control_the_shipped_default_sends_the_address(monkeypatch):
    harness, _runtime = _captured(monkeypatch)
    with model_call_scope(session_call(None)):
        await harness.driver.chat(messages=[{"role": "user", "content": PROMPT}], model=harness.model)
    assert IP in harness.sent()[0]


async def test_chat_pre_turn_task_extraction(client, db, monkeypatch):
    from app.web._helpers import chat_turn_start

    workspace = await _workspace(db)
    harness, runtime = _captured(monkeypatch)
    monkeypatch.setattr(chat_turn_start, "gate", lambda *_args: None)

    async def client_kwargs(_db, _provider):
        return {"driver": "openai_compatible", "provider_name": "direct"}

    monkeypatch.setattr(chat_turn_start, "build_provider_client_kwargs_async", client_kwargs)
    session = SimpleNamespace(id=str(uuid.uuid4()), project_id=workspace, user_id=None)
    await chat_turn_start._dispatch_task_extraction(
        db, session=session, candidates=[(SimpleNamespace(id="p", name="direct"), runtime["model"])],
        snapshot=SimpleNamespace(for_ref=lambda *_args: None), scope=None,
        llm_messages=[{"role": "user", "content": PROMPT}])
    _stored_action_applied(harness)


async def test_workflow_proposal_model(client, db, monkeypatch):
    from app.services.workflow_routing import proposal_model

    workspace = await _workspace(db)
    harness, runtime = _captured(monkeypatch)

    async def workspace_runtimes(_db, project_id):
        assert project_id == workspace
        return [dict(runtime)]

    monkeypatch.setattr(proposal_model, "_workspace_runtimes", workspace_runtimes)
    model = await proposal_model.governed_proposal_model(db, project_id=workspace)
    await model.answer(system="Pick a workflow.", user=PROMPT)
    _stored_action_applied(harness)


async def test_company_workflow_review(client, db, monkeypatch):
    from app.services.workflow_routing import proposal_model
    from app.services.workflow_runs.review import model as review_model

    workspace = await _workspace(db)
    harness, runtime = _captured(monkeypatch)

    async def workspace_runtimes(_db, _project_id):
        return [dict(runtime)]

    async def chosen(_db, _runtimes, _model):
        return []

    monkeypatch.setattr(proposal_model, "_workspace_runtimes", workspace_runtimes)
    monkeypatch.setattr(review_model, "_chosen_model_runtimes", chosen)
    model = await review_model.company_review_model(db, project_id=workspace, model=runtime["model"])
    await model.answer(system="Review the run.", user=PROMPT)
    _stored_action_applied(harness)


@pytest.mark.parametrize("factory", ["answer", "research", "capture", "episode_summary"])
async def test_knowledge_answer_research_capture_and_episode_summary(factory, client, db, monkeypatch):
    from app.services.knowledge.answer.model import governed_answer_model
    from app.services.knowledge.episodes.summary_model import governed_summary_model
    from app.services.knowledge.memory.capture_model import governed_capture_model
    from app.services.knowledge.research.model import governed_research_model

    workspace = await _workspace(db)
    harness, _runtime = _captured(monkeypatch)
    build = {"answer": governed_answer_model, "research": governed_research_model,
             "capture": governed_capture_model, "episode_summary": governed_summary_model}[factory]
    model = await build(db, project_id=workspace)
    assert await model.json(system="Answer in JSON.", user=PROMPT) == {"answer": "ok", "memories": [],
                                                                       "summary": "ok"}
    _stored_action_applied(harness)


async def test_knowledge_graph_extraction(client, db, monkeypatch):
    from app.services.knowledge_graph.llm_runtime import build_generate_fn

    workspace = await _workspace(db)
    harness, _runtime = _captured(monkeypatch)
    generate = await build_generate_fn(db, project_ids=workspace)
    await generate(PROMPT)
    _stored_action_applied(harness)


async def test_knowledge_temporal_extraction(client, db, monkeypatch):
    from app.services.knowledge.temporal import graphiti_llm

    workspace = await _workspace(db)
    harness, runtime = _captured(monkeypatch)

    async def select(_db, *, project_id):
        assert project_id == workspace
        return [dict(runtime)]

    monkeypatch.setattr(graphiti_llm, "select_graph_runtimes", select)
    llm = await graphiti_llm.governed_graph_llm(db, project_id=workspace)
    await llm._generate_response([SimpleNamespace(role="user", content=PROMPT)])
    _stored_action_applied(harness)


@pytest.mark.parametrize("with_tools", [False, True])
async def test_teams_call_agent(with_tools, client, db, monkeypatch):
    from app.services.call_agent import service as call_agent_service

    workspace = await _workspace(db)
    harness, runtime = _captured(monkeypatch, reply="Done.")

    async def admitted(_db, *, project_id, configured_model, model):
        assert project_id == workspace
        return harness.driver, runtime["model"]

    monkeypatch.setattr(call_agent_service, "resolve_admitted_provider", admitted)
    agent = call_agent_service.CallAgentService(db, SimpleNamespace(id="c-1", project_id=workspace, llm_model=None,
                                                                    enabled_tools=[]))
    messages = [{"role": "user", "content": PROMPT}]
    if with_tools:
        tools = [{"type": "function", "function": {"name": "lookup", "description": "Look up a task.",
                                                   "parameters": {"type": "object", "properties": {}}}}]
        await agent._llm_with_tools(messages, tools)
    else:
        await agent._llm_chat(messages)
    _stored_action_applied(harness)
