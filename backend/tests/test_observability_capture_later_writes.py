"""Observability O8 review fix: the capture policy also covers the writes after a tool ran.

A turn with a tool call rewrites its ``turn_traces`` row after the tools ran (the native loop's tool follow-up, the
harness's turn recorder): tool results and the full context. Those writes pass the same capture policy as the
first write, so a ``minimal`` Workspace stores no content and every mode redacts secrets.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.agent.engine import run_agent
from app.models import Project, TurnTrace, User
from app.models import Session as AgentSession
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY
from tests.run_capability_support import UNDECLARED_READ_ONLY_RUN

TOOL = "get_current_time"
SECRET = ("sk-li" + "ve-abcdefghijklmnopqrstu0123")
TOOL_CALL = {"id": "call_1", "type": "function", "function": {"name": TOOL, "arguments": "{}"}}
SCRIPT = (
    {"content": "", "tool_calls": [TOOL_CALL], "usage": {"prompt_tokens": 11, "completion_tokens": 3}},
    {"content": "It is midnight UTC.", "tool_calls": None, "usage": {"prompt_tokens": 17, "completion_tokens": 5}},
)


@pytest.fixture
def scripted_tool_turn(monkeypatch):
    """A tool whose result carries a secret, and a provider that calls it once and then answers."""

    async def leaky_time(params, context):
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "note": f"api_key={SECRET}"}

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", leaky_time)
    script: list[dict[str, Any]] = []
    original_prepare = engine_module._prepare_agent_run

    async def prepare_with_the_tool(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = [get_all_definitions()[TOOL]]
        return prepared

    def provider_factory(**_kwargs):
        class _ScriptedProvider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                return {**script.pop(0), "model": model or ""}

            async def close(self):
                return None

        return _ScriptedProvider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare_with_the_tool)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return script


async def _traces_of_a_tool_turn(db, monkeypatch, script, *, mode: str) -> list[TurnTrace]:
    script[:] = list(SCRIPT)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=str(uuid.uuid4()), name=f"capture-{uuid.uuid4().hex[:8]}",
                      config={"trace_capture": {"mode": mode}})
    session = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, project_id=project.id, agent_type="chat",
                           metadata_=dict(UNDECLARED_READ_ONLY_RUN))
    db.add_all([project, session])
    await db.commit()
    session_id, project_id, admin_id = session.id, project.id, admin.id
    async for _event in run_agent(session_id=session_id, user_message="What time is it?", user_id=admin_id,
                                  project_id=project_id, agent_type="chat", db=db):
        pass
    await db.commit()
    assert script == [], "the tool call and the answer both ran"
    return list((await db.execute(
        select(TurnTrace).where(TurnTrace.session_id == session_id).execution_options(populate_existing=True)
    )).scalars())


@pytest.mark.asyncio
async def test_minimal_stores_no_content_after_the_tool_ran(db, monkeypatch, scripted_tool_turn):
    traces = await _traces_of_a_tool_turn(db, monkeypatch, scripted_tool_turn, mode="minimal")

    assert traces
    for trace in traces:
        assert trace.tool_trace_json == [] and trace.input_messages_json == []
        assert trace.context_snapshot_json.get("capture") == "metadata_only"
        assert not {"system_prompt", "memory_prompt", "skills_prompt"} & set(trace.context_snapshot_json)
        assert "content" not in trace.raw_output
        assert SECRET not in str([trace.tool_trace_json, trace.context_snapshot_json, trace.raw_output])


@pytest.mark.asyncio
async def test_standard_keeps_the_tool_result_and_redacts_its_secret(db, monkeypatch, scripted_tool_turn):
    traces = await _traces_of_a_tool_turn(db, monkeypatch, scripted_tool_turn, mode="standard")

    with_tools = [trace for trace in traces if trace.tool_trace_json]
    assert with_tools, "the tool batch was written back to the trace"
    assert [item["tool_name"] for item in with_tools[0].tool_trace_json] == [TOOL]
    assert SECRET not in str([(trace.tool_trace_json, trace.context_snapshot_json) for trace in traces])
