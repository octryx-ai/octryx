"""Real turns: delegated runtimes are refused, and the model is always told the format.

- A flow-definition session hands the turn to another runtime after admission, so a ``json_object`` agent there is refused as
  ``needs_configuration`` / ``agent_reply_contract_path_unsupported`` before any model call and before
  that runtime starts.
- Whenever the check is enforced the system prompt carries ``## Reply Format`` exactly once, also
  when the plan leaves the blueprint out and on the ``bounded_evidence`` variant, which carries no
  agent sections; a free-text agent never gets the section.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.agent.core.context.run_context_knowledge as run_context_knowledge_module
from app.agent.core.prompts.agent_blueprint import REPLY_FORMAT_HEADING
from tests.agent_reply_contract_runtime_support import FENCED, VALID, _checked_agent, _final_trace
from tests.agent_tool_surface_runtime_support import _agent, _run, _Script, _session

PATH_UNSUPPORTED = ("needs_configuration", "agent_reply_contract_path_unsupported")


async def _profile(db, session) -> tuple[str, str]:
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    return profile["status"], profile.get("reason_code")


@pytest.mark.asyncio
async def test_a_flow_definition_session_refuses_a_checked_agent_before_the_orchestrator(db, monkeypatch):
    import app.services.flow_orchestration.runner as runner_module
    from tests.flow_agent_step_support import _admin_and_project, _flow

    orchestrated: list[str] = []

    async def fake_execute_flow_version(**kwargs):
        orchestrated.append(kwargs.get("flow_version_id"))
        raise AssertionError("the flow orchestrator must not start for a checked agent")

    monkeypatch.setattr(runner_module, "execute_flow_version", fake_execute_flow_version)
    admin, project = await _admin_and_project(db)
    version = await _flow(db, admin, project.id, {"prompt": "Summarise."})
    _admin, session = await _session(db, project.id)
    session.flow_definition_version_id = version.id
    await db.commit()
    script = _Script(monkeypatch, [{"content": VALID, "tool_calls": None}])

    await _run(db, admin, session, agent_definition=_checked_agent())

    assert script.calls == [] and orchestrated == []
    assert await _profile(db, session) == PATH_UNSUPPORTED


def _plan_variant(monkeypatch, **overrides):
    original = run_context_knowledge_module.plan_turn_context

    def planned(*args, **kwargs):
        return dataclasses.replace(original(*args, **kwargs), **overrides)

    monkeypatch.setattr(run_context_knowledge_module, "plan_turn_context", planned)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [{}, {"include_agent_blueprint": False}, {"system_prompt_variant": "bounded_evidence"}],
    ids=["blueprint", "no-blueprint", "bounded-evidence"],
)
async def test_an_enforced_check_always_tells_the_model_the_format(db, monkeypatch, overrides):
    from app.services.session.turn_execution_summary import runtime_outcome_from_trace

    _plan_variant(monkeypatch, **overrides)
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": FENCED, "tool_calls": None}])

    await _run(db, admin, session, agent_definition=_checked_agent())

    system = "\n".join(script.calls[0]["system"])
    assert system.count(REPLY_FORMAT_HEADING) == 1 and '"total": <integer>' in system
    trace = await _final_trace(db, session.id)
    assert runtime_outcome_from_trace(trace.context_snapshot_json, trace.raw_output) == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{}, {"include_agent_blueprint": False}], ids=["blueprint", "no-blueprint"])
async def test_a_free_text_agent_never_gets_the_format_section(db, monkeypatch, overrides):
    _plan_variant(monkeypatch, **overrides)
    admin, session = await _session(db)
    script = _Script(monkeypatch, [{"content": FENCED, "tool_calls": None}])

    await _run(db, admin, session, agent_definition=_agent(None))

    assert REPLY_FORMAT_HEADING not in "\n".join(script.calls[0]["system"])
