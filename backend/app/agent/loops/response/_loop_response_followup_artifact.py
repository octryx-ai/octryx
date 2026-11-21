"""Unsatisfied workflow-artifact-contract guard of ``handle_followup_response_guards``."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt
from ._loop_response_followup_inputs import FollowupGuardInputs, remind_and_continue_or_stop

# A knowledge workflow answers a question from retrieved evidence - it must never be told the
# "contract requires a finished artifact", or the model fabricates a deliverable (e.g. a generic .md
# with cold-start reasoning) instead of answering.
_NON_ARTIFACT_KNOWLEDGE_WORKFLOWS = frozenset({"knowledge_request"})

# Unsatisfied-contract instruction key per workflow (``loop.followup.instruction.<key>``); any other
# workflow gets ``other`` (retrieve evidence, no unrequested deliverable).
_FOLLOWUP_INSTRUCTION_KEYS = {"knowledge_request": "knowledge_request"}


def _artifact_instruction(run: FollowupGuardInputs) -> str:
    # A workflow without its own key gets ``other``: retrieve evidence first, and it is never told
    # to build a deck.
    return render_prompt(f"loop.followup.instruction.{_FOLLOWUP_INSTRUCTION_KEYS.get(run.workflow_id, 'other')}")


async def unsatisfied_artifact_contract_guard(
    run: FollowupGuardInputs, workflow_contract: dict[str, Any]
) -> dict[str, Any]:
    artifact_path = str(workflow_contract.get("artifact_path") or "").strip()
    artifact_instruction = _artifact_instruction(run)
    requires_artifact = run.workflow_id not in _NON_ARTIFACT_KNOWLEDGE_WORKFLOWS
    if not requires_artifact:
        requirement = render_prompt("loop.followup.evidence_required")
    elif artifact_path:
        requirement = render_prompt("loop.followup.artifact_required_at", artifact_path=artifact_path)
    else:
        requirement = render_prompt("loop.followup.artifact_required")
    return await remind_and_continue_or_stop(
        run,
        reminder=requirement + " " + artifact_instruction,
        raw_output={
            "content": run.content,
            "tool_calls": [],
            "runtime_attempts": run.runtime_attempts,
            "suppressed_for_unsatisfied_workflow_artifact_contract": True,
            "workflow_id": workflow_contract.get("workflow_id"),
            "artifact_path": artifact_path,
        },
    )
