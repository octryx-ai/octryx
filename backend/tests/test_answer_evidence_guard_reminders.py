"""The guard reminds an uncited or invented-link answer once, then delivers it with a sources note or marker."""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_answer_evidence import handle_answer_evidence_guard
from app.services.answer_evidence.record import ANSWER_EVIDENCE_KEY, read_answer_evidence
from app.services.answer_evidence.texts import REMINDER_MARKER, guard_text
from tests.answer_evidence_guard_support import CITED_PETCLINIC, PETCLINIC_OWNER, UNCITED_PETCLINIC, _web_fetch_result

# --- the runtime boundary --------------------------------------------------------------------------


class _Db:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)


async def _guard(
    content: str, history: list[dict], messages: list[dict], *, tool_calls=None, capability="diagnosis", user="Explain Owner"
):
    traces, finals, snapshot = _Recorder(), _Recorder(), {}
    outcome = await handle_answer_evidence_guard(
        db=_Db(),
        session_id="s1",
        runtime={"provider_name": "bedrock"},
        response={"usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        request_messages=[{"role": "user", "content": user}],
        messages=messages,
        context_snapshot=snapshot,
        runtime_attempts=[],
        runtime_settings={},
        usage_model="sonnet",
        content=content,
        tool_calls=tool_calls,
        capability_type=capability,
        has_followup_steps=False,
        sub_agent_depth=0,
        turn_tool_history=history,
        persist_turn_trace=traces,
        persist_traced_assistant_message=finals,
    )
    return outcome, snapshot.get(ANSWER_EVIDENCE_KEY), traces.calls, finals.calls


@pytest.mark.asyncio
async def test_facts_without_links_are_reminded_once_then_delivered_with_the_sources_note() -> None:
    messages: list[dict] = []
    outcome, record, traces, finals = await _guard(UNCITED_PETCLINIC, [_web_fetch_result()], messages)
    assert outcome == {"action": "continue"}
    assert record["evidence_guard"] == "reminded" and record["uncited_count"] == 2
    assert messages[-1]["role"] == "system" and messages[-1]["content"].startswith(REMINDER_MARKER)
    assert traces[0]["raw_output"]["suppressed_for_answer_evidence"] is True and not finals

    outcome, record, traces, finals = await _guard(UNCITED_PETCLINIC, [_web_fetch_result()], messages)
    # Never withheld: the answer is delivered, with one note naming the sources it did not link.
    assert outcome["action"] == "mark" and not finals
    assert record == {
        "evidence_guard": "marked",
        "cited_count": 0,
        "uncited_count": 2,
        "invented_url_count": 0,
        "evidence_url_count": 1,
        "reminder_count": 1,
    }
    delivered = outcome["content"]
    assert delivered.startswith(UNCITED_PETCLINIC.rstrip()) and "withheld" not in delivered
    assert "No source linked" in delivered and f"[Owner.java]({PETCLINIC_OWNER})" in delivered


@pytest.mark.asyncio
async def test_an_invented_url_is_reminded_then_delivered_with_the_link_named() -> None:
    messages: list[dict] = []
    invented = "Owner keeps its pets in a list, see [the docs](https://docs.example.com/petclinic/owner) for details."
    first, record, _, _ = await _guard(invented, [_web_fetch_result()], messages)
    assert first == {"action": "continue"} and record["invented_url_count"] == 1
    assert "https://docs.example.com/petclinic/owner" in messages[-1]["content"]
    outcome, record, _, finals = await _guard(invented, [_web_fetch_result()], messages)
    assert outcome["action"] == "mark" and record["evidence_guard"] == "marked" and not finals
    assert outcome["content"].startswith(invented)
    assert "did not come from this turn's sources: https://docs.example.com/petclinic/owner" in outcome["content"]


@pytest.mark.asyncio
async def test_a_cited_answer_after_the_reminder_passes() -> None:
    messages = [{"role": "system", "content": guard_text("evidence_guard.reminder", details="")}]
    outcome, record, traces, finals = await _guard(CITED_PETCLINIC, [_web_fetch_result()], messages)
    assert outcome is None and not traces and not finals
    assert (record["evidence_guard"], record["reminder_count"]) == ("passed", 1)


@pytest.mark.asyncio
async def test_a_greeting_without_evidence_is_delivered_with_the_unsourced_marker() -> None:
    outcome, record, traces, finals = await _guard("Hello! How can I help you today?", [], [])
    assert outcome is None and not traces and not finals
    assert record["evidence_guard"] == "unsourced"


@pytest.mark.asyncio
async def test_a_reply_with_tool_calls_is_not_checked() -> None:
    outcome, record, _, _ = await _guard(UNCITED_PETCLINIC, [_web_fetch_result()], [], tool_calls=[{"id": "c1"}])
    assert outcome is None and record is None


@pytest.mark.asyncio
async def test_a_change_turns_delivery_report_is_not_checked() -> None:
    # The mode of work is the explicit scope: a change turn reports its own actions (diff, gates).
    outcome, record, _, _ = await _guard(UNCITED_PETCLINIC, [_web_fetch_result()], [], capability="change")
    assert outcome is None and record is None
    outcome, record, _, _ = await _guard(UNCITED_PETCLINIC, [_web_fetch_result()], [], capability="plan")
    assert outcome == {"action": "continue"} and record["evidence_guard"] == "reminded"


def test_the_trace_record_reader_keeps_only_closed_values() -> None:
    assert read_answer_evidence({ANSWER_EVIDENCE_KEY: {"evidence_guard": "maybe"}}) is None
    read = read_answer_evidence({ANSWER_EVIDENCE_KEY: {"evidence_guard": "passed", "cited_count": "3", "uncited_count": 0}})
    assert read["evidence_guard"] == "passed" and read["cited_count"] is None and read["uncited_count"] == 0
