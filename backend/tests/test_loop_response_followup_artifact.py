"""Regression: the artifact-completion follow-up must not tell a
non-artifact workflow (e.g. ``knowledge_request``) to build a presentation deck.

Root cause of the persistent "check out Alice Example" failure: the follow-up
guard's catch-all ``else`` assumed a presentation artifact for ANY workflow that
reached it, so a plain knowledge question got primed with
"curate the storyline / build the deck with build_presentation_script /
finished artifact". That instruction is injected mid-loop and poisoned every
model (Nova, Claude Haiku, MiniMax). It must instead tell knowledge workflows to
retrieve evidence and answer.
"""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_response_followup import handle_followup_response_guards
from app.agent.loops.response._loop_response_followup_inputs import FollowupGuardInputs


async def _noop_async(*_args, **_kwargs):
    return None


def _invoke(*, workflow_id: str, messages: list[dict]):
    """Drive handle_followup_response_guards into the artifact-contract branch.

    All earlier branches are skipped: no tool calls, empty tool history, no
    evidence axes, no tdd / self-review step. The artifact contract is reported
    unsatisfied so the follow-up reminder is produced and appended to ``messages``.
    """
    return handle_followup_response_guards(FollowupGuardInputs(
        db=None,
        session_id="s",
        runtime={"provider_name": "p"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="m",
        content="Here is what I found...",
        tool_calls=None,
        current_step=None,
        current_turn_content="Check out Alice Example and what DevOps work he does.",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[],
        step_tool_history=[],
        executed_tool_names=set(),
        covered_evidence_axes=set(),
        workflow_contract={"workflow_id": workflow_id},
        workflow_id=workflow_id,
        tdd_cycle_state=None,
        consecutive_non_progress_response_count=0,
        consecutive_coding_no_execution_count=0,
        consecutive_transitional_response_count=0,
        persist_suppressed_runtime_response=_noop_async,
        persist_traced_assistant_message=_noop_async,
        build_stalled_step_message=lambda _step: "",
        build_tdd_cycle_incomplete_reminder=lambda _a, _b: "",
        build_initial_tdd_cycle_state=lambda: {},
        is_tdd_cycle_complete=lambda _s: True,
        is_tdd_cycle_step=lambda _s: False,
        _is_self_review_step=lambda _s: False,
        _is_self_review_step_complete=lambda _s, _h: True,
        _build_incomplete_self_review_reminder=lambda _s: "",
        workflow_artifact_contract_satisfied=lambda _contract, **_k: False,
    ))


@pytest.mark.asyncio
async def test_knowledge_request_followup_asks_for_evidence_not_a_deck():
    messages: list[dict] = []
    result = await _invoke(workflow_id="knowledge_request", messages=messages)

    assert result["action"] == "continue"
    reminder = messages[-1]["content"]
    assert messages[-1]["role"] == "system"
    # Must not poison a plain knowledge question with presentation framing.
    assert "build_presentation_script" not in reminder
    assert "build the deck" not in reminder.lower()
    assert "storyline" not in reminder.lower()
    assert "finished artifact" not in reminder.lower()
    assert "requires a finished artifact" not in reminder.lower()
    # The only mention of a deck is the explicit prohibition.
    assert "do not build or promise a deliverable" in reminder.lower()
    # Must steer to governed evidence retrieval instead.
    assert "knowledge_search" in reminder
    assert "knowledge_search /" not in reminder
    assert "grounding evidence" in reminder
