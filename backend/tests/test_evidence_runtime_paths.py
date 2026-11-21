"""E1c: the answer evidence governance on every runtime path.

1. Sub-agent consolidation: ``get_context_from_subthreads`` carries each accepted child's sources up,
   so the parent answer is checked against the union of its own and its children's evidence; a link
   no tool result carried is still invented.
2. Native-loop turns run the answer evidence guard and the inline pseudo-tool-call guard at the
   turn boundary.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

import app.agent.engine as engine_module
from app.agent.loops.response._loop_pseudo_tool_calls import PSEUDO_TOOL_CALL_REFUSAL_REASON
from app.models import Message, ToolCall, TurnTrace, User
from app.models import Session as AgentSession
from app.services.answer_evidence.check import REFUSAL_REASON_INVENTED_URL, check_answer_evidence
from app.services.answer_evidence.child_evidence import child_evidence_sources
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.answer_evidence.record import read_answer_evidence
from app.services.tool_result_compression.strategy_documents import _compress_subthread_context
from app.tools.registry import TOOL_REGISTRY
from app.tools.sub_agent import GetContextFromSubthreadsTool
from tests.evidence_runtime_support import _SCENARIO_OVERRIDES, _evidence_scenario  # noqa: F401 - autouse fixture
from tests.harness_runtime_support import TOOL, fake_world  # noqa: F401 - fixture
from tests.test_harness_runtime_parity import TOOL_RESPONSE, _run_turn

DOC = "https://docs.example.test/runbook/failover"


# --- sub-agent consolidation -------------------------------------------------------------------------


def _call(status: str, result: Any) -> SimpleNamespace:
    return SimpleNamespace(tool_name="web_fetch", status=status, result=result)


def test_child_sources_come_from_successful_tool_calls_including_externalized_results() -> None:
    fetched = {"url": DOC, "source_url": DOC, "cite_as": f"[Failover runbook]({DOC})"}
    pointer = {
        "_artifact_storage": "external_json_gzip",
        "preview": {"compact_result": {"results": [{"source_url": "https://wiki.example.test/p/2", "cite_as": "[P2](https://wiki.example.test/p/2)"}]}},
    }
    sources = child_evidence_sources(
        [_call("success", fetched), _call("success", pointer), _call("error", {"source_url": "https://bad.example/x"})]
    )
    assert [source["cite_as"] for source in sources] == [f"[Failover runbook]({DOC})", "[P2](https://wiki.example.test/p/2)"]


@pytest.mark.asyncio
async def test_a_parent_answer_citing_child_evidence_passes_and_an_invented_url_is_refused(db, monkeypatch) -> None:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    parent = AgentSession(id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", status="running")
    child = AgentSession(
        id=str(uuid.uuid4()), user_id=admin.id, agent_type="chat", status="completed", parent_session_id=parent.id
    )
    db.add_all([parent, child])
    await db.flush()
    db.add(Message(id=str(uuid.uuid4()), session_id=child.id, role="user", content="Find the failover runbook"))
    db.add(Message(id=str(uuid.uuid4()), session_id=child.id, role="assistant", content="The drill runs quarterly."))
    db.add(
        ToolCall(
            id=str(uuid.uuid4()), session_id=child.id, tool_name="web_fetch", status="success",
            result={"url": DOC, "source_url": DOC, "cite_as": f"[Failover runbook]({DOC})", "content": "quarterly"},
        )
    )
    await db.commit()

    def accepted_record(**kwargs):
        return {"session_id": kwargs["session"].id, "final_response": kwargs["final_response"], "quality": {"accepted": True}}

    monkeypatch.setattr("app.tools.sub_agent.build_sub_agent_evidence_record", accepted_record)
    context = SimpleNamespace(db=db, session_id=parent.id)
    result = await GetContextFromSubthreadsTool().execute({}, context)
    assert result["accepted_subthreads"][0]["evidence_sources"] == [{"source_url": DOC, "cite_as": f"[Failover runbook]({DOC})"}]

    # The parent sees the compressed result: the sources survive compression.
    compact = _compress_subthread_context(result, {})
    evidence = collect_turn_evidence([{"tool_name": "get_context_from_subthreads", "result": compact}])
    assert evidence.evidence_bearing

    cited = check_answer_evidence(f"The failover drill runs every quarter ([runbook]({DOC})).", evidence)
    assert cited.satisfied
    invented = check_answer_evidence("The failover drill runs every quarter ([runbook](https://invented.example/x)).",
                                     evidence)
    assert not invented.satisfied and invented.refusal_reason == REFUSAL_REASON_INVENTED_URL


# --- HarnessRuntime ----------------------------------------------------------------------------------------

SOURCED_TOOL_RESULT = {"utc_time_iso": "2026-09-30T00:00:00+00:00", "source_url": DOC, "cite_as": f"[Clock page]({DOC})"}
UNCITED = {"content": "It is midnight UTC on the reference clock, which the platform reads every minute.",
           "tool_calls": None, "usage": {"prompt_tokens": 17, "completion_tokens": 5}}
CITED = {"content": f"It is midnight UTC on the reference clock ([Clock page]({DOC})).", "tool_calls": None,
         "usage": {"prompt_tokens": 17, "completion_tokens": 5}}
PSEUDO = {"content": '```tool_use\nget_world_clock\n{"zone": "UTC"}\n```', "tool_calls": None,
          "usage": {"prompt_tokens": 17, "completion_tokens": 5}}


def _sourced_tool(monkeypatch) -> None:
    async def sourced_time(params, context):
        return dict(SOURCED_TOOL_RESULT)

    monkeypatch.setattr(TOOL_REGISTRY[TOOL], "execute", sourced_time)
    # The clock tool's own compactor keeps only the time fields; this test tool is a sourced read.
    monkeypatch.setattr(engine_module, "_compact_tool_result_for_model", lambda _name, result: dict(result))


async def _outcome(db, session_id: str) -> tuple[str, list[dict], list[str]]:
    rows = (
        await db.execute(select(Message).where(Message.session_id == session_id, Message.role == "assistant").order_by(Message.created_at))
    ).scalars().all()
    traces = (
        await db.execute(select(TurnTrace).where(TurnTrace.session_id == session_id).order_by(TurnTrace.created_at))
    ).scalars().all()
    records = [record for trace in traces if (record := read_answer_evidence(trace.context_snapshot_json))]
    reasons = [str(trace.raw_output.get("refusal_reason")) for trace in traces if (trace.raw_output or {}).get("refusal_reason")]
    return str(rows[-1].content or ""), records, reasons


@pytest.mark.asyncio
async def test_an_uncited_answer_is_reminded_then_delivered_marked_on_the_native_loop(db, monkeypatch, fake_world) -> None:  # noqa: F811
    """Never withheld: after the one reminder the answer is delivered with a sources note."""
    _sourced_tool(monkeypatch)
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [TOOL_RESPONSE, UNCITED, UNCITED])
    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, records, reasons = await _outcome(db, session_id)
    assert "withheld" not in final and "every minute" in final
    assert "No source linked" in final and DOC in final
    assert [record["evidence_guard"] for record in records][-2:] == ["reminded", "marked"]
    assert reasons == []


@pytest.mark.asyncio
async def test_a_cited_answer_passes_on_the_native_loop(db, monkeypatch, fake_world) -> None:  # noqa: F811
    _sourced_tool(monkeypatch)
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [TOOL_RESPONSE, CITED])
    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, records, reasons = await _outcome(db, session_id)
    assert final == CITED["content"] and records[-1]["evidence_guard"] == "passed" and reasons == []


@pytest.mark.asyncio
async def test_a_pseudo_tool_call_answer_is_refused_on_the_native_loop(db, monkeypatch, fake_world) -> None:  # noqa: F811
    monkeypatch.setitem(_SCENARIO_OVERRIDES, "script", [PSEUDO, PSEUDO])
    session_id, _events = await _run_turn(db, monkeypatch, fake_world, runtime="native", scenario="evidence")

    final, _records, reasons = await _outcome(db, session_id)
    assert "wrote tool calls as text" in final and "tool_use" not in final
    assert reasons == [PSEUDO_TOOL_CALL_REFUSAL_REASON]

