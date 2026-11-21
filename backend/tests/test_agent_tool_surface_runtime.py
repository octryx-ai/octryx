"""The agent tool surface at runtime: the real ``run_agent`` loop with a scripted provider.

- ``none``: one model call with zero tool definitions and no model workflow catalog. A
  model-fabricated tool call is refused at dispatch and nothing is executed. A selected workflow
  that needs tools, or an unknown value, stops the turn before any model call.
- ``governed``: tools are offered and executed, and policy denials and
  approvals keep their behaviour.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models import ToolCall
from app.services.workflow_routing.model_catalog import MODEL_WORKFLOW_CATALOG_PROMPT_MARKER
from tests.agent_tool_surface_runtime_support import _ANSWER, _agent, _record_tool_executions, _run, _Script, _session
from tests.test_zero_tool_turn import _workspace_with_selected_definition

_CATALOG_PROMPT = MODEL_WORKFLOW_CATALOG_PROMPT_MARKER


# --- direct text-only ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_text_only_agent_answers_in_one_call_without_any_tool_definition(db, monkeypatch):
    # A real-world shape: a first answer that a tool-offering turn would have suppressed as a
    # transition ("I'll complete this workflow step ..."). Without tools it is the final answer.
    first = "I'll complete this workflow step by following the configured goal.\n\n31 + 8 + 4 = 43\n\nSUM=43"
    script = _Script(monkeypatch, [{"content": first, "tool_calls": None}])
    admin, session = await _session(db)

    contents = await _run(db, admin, session, agent_definition=_agent("none"))

    assert len(script.calls) == 1
    assert script.calls[0]["tools"] == []
    # The model workflow catalog does not reach the model.
    assert not any(_CATALOG_PROMPT in text for text in script.calls[0]["system"])
    assert contents[-1] == first
    await db.refresh(session)
    assert session.metadata_["tool_surface_source"] == "agent_no_tools"
    assert session.metadata_["execution_profile"]["status"] == "allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["governed", None])
async def test_a_governed_agent_still_offers_its_governed_tools(db, monkeypatch, surface):
    # None: a payload without the key is governed.
    script = _Script(monkeypatch, [{"content": _ANSWER, "tool_calls": None}])
    admin, session = await _session(db)

    await _run(db, admin, session, agent_definition=_agent(surface))

    assert script.calls and script.calls[0]["tools"], "governed keeps today's surface"
    # The same harness sees the catalog for a governed agent, so its absence above is meaningful.
    assert any(_CATALOG_PROMPT in text for text in script.calls[0]["system"])
    await db.refresh(session)
    assert session.metadata_["tool_surface_source"] == "governed_default"


# --- fabricated and real tool work --------------------------------------------


@pytest.mark.asyncio
async def test_a_fabricated_tool_call_of_a_text_only_agent_is_refused_and_nothing_runs(db, monkeypatch):
    executed = _record_tool_executions(monkeypatch)
    fabricated = {
        "id": "call-fabricated",
        "type": "function",
        "function": {"name": "knowledge_search", "arguments": json.dumps({"query": "numbers"})},
    }
    script = _Script(monkeypatch, [{"content": "", "tool_calls": [fabricated]}, {"content": _ANSWER, "tool_calls": None}])
    admin, session = await _session(db)

    contents = await _run(db, admin, session, agent_definition=_agent("none"))

    assert executed == [], "no tool may run for a text-only agent"
    assert all(call["tools"] == [] for call in script.calls)
    assert contents[-1] == _ANSWER
    rows = (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all()
    assert [row.tool_name for row in rows] == ["knowledge_search"], "the refusal is recorded like any tool call"
    for row in rows:
        result = row.result if isinstance(row.result, dict) else json.loads(row.result or "{}")
        assert result.get("tool_execution", {}).get("policy") == "agent_tool_surface"


@pytest.mark.asyncio
async def test_a_governed_agent_still_executes_a_real_tool_call(db, monkeypatch):
    executed = _record_tool_executions(monkeypatch)
    call = {
        "id": "call-real",
        "type": "function",
        "function": {"name": "get_current_time", "arguments": "{}"},
    }
    script = _Script(monkeypatch, [{"content": "", "tool_calls": [call]}, {"content": _ANSWER, "tool_calls": None}])
    admin, session = await _session(db)

    await _run(db, admin, session, agent_definition=_agent("governed"))

    assert executed == ["get_current_time"]
    assert len(script.calls) == 2


# --- fail closed before model work --------------------------------------------


@pytest.mark.asyncio
async def test_a_text_only_agent_with_a_selected_workflow_needs_configuration_before_the_model(db, monkeypatch):
    admin, project, session, message = await _workspace_with_selected_definition(
        db, project_config={"enabled_connectors": ["jira"]}, jira_tool_config=True
    )
    script = _Script(monkeypatch, [])

    contents = await _run(db, admin, session, agent_definition=_agent("none"), message=message)

    assert script.calls == [], "the workflow must not silently widen No tools, nor run without its tools"
    await db.refresh(session)
    profile = session.metadata_["execution_profile"]
    assert profile["status"] == "needs_configuration"
    assert profile["reason_code"] == "agent_tool_surface_workflow_conflict"
    assert contents and "No tools (text only)" in contents[-1]
    assert (await db.execute(select(ToolCall).where(ToolCall.session_id == session.id))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["text", "", None, " none"])
async def test_an_unknown_tool_surface_value_stops_before_the_model(db, monkeypatch, invalid):
    script = _Script(monkeypatch, [])
    admin, session = await _session(db)
    agent = _agent(None)
    agent["toolSurface"] = invalid  # present but not an enum value: never read as governed

    await _run(db, admin, session, agent_definition=agent)

    assert script.calls == []
    await db.refresh(session)
    assert session.metadata_["execution_profile"]["reason_code"] == "agent_tool_surface_invalid"
