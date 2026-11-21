"""Hook stdout of the Stop gate (``hooks.run_stop``): the verification answer, the consecutive-block cap and the
unread board reminder."""

from __future__ import annotations

from typing import Any

from .hook_outputs import _bounded_text, _codes
from .platform import PlatformResult

STOP_BLOCK_CAP = 3
STATE_NEXT_PHASE = "next_phase"  # the platform's ``octryx/same_turn``: go on with the next phase in this turn
MAX_PHASE_PROMPT_CHARS = 4000  # the next phase's prompt (``next_phase``), before its compact contract


def is_internal_subagent(hook_input: dict[str, Any]) -> bool:
    """A SubagentStop of Claude Code's own forked helper (the conversation compaction, ``querySource: compact``), not
    of an agent the model started.

    Claude Code sends ``agent_type`` with every SubagentStop: the Task agent's type, ``""`` for its own forks (e.g.
    its compaction), which have no type and are not judged like a sub-agent doing the phase's work. A SubagentStop
    without ``agent_type`` keeps the gate."""
    if str(hook_input.get("hook_event_name") or "") != "SubagentStop" or "agent_type" not in hook_input:
        return False
    return not str(hook_input.get("agent_type") or "").strip()


def _chain_key(hook_input: dict[str, Any]) -> str:
    event = str(hook_input.get("hook_event_name") or "Stop")
    agent = str(hook_input.get("agent_id") or "main")
    return f"{event}:{agent}"[:200]


def stop_output(
    result: PlatformResult,
    *,
    stop_hook_active: bool,
    prior_blocks: int,
    cap: int = STOP_BLOCK_CAP,
) -> tuple[dict[str, Any] | None, int]:
    """Hook stdout for a verification result plus the new consecutive-block count."""
    blocks = prior_blocks if stop_hook_active else 0
    if result.outcome != "ok":
        return (
            {"systemMessage": f"Octryx verification gate unreachable{_codes(result)}; "
             "stopping without verification."},
            0,
        )
    state = result.state
    if state in ("passed", "not_applicable"):
        return None, 0
    if state == STATE_NEXT_PHASE:  # the run's class goes on with the next phase in this turn (``same_turn``)
        return {"decision": "block", "reason": _bounded_text(result.body.get("detail"), MAX_PHASE_PROMPT_CHARS)
                or "Go on with the next phase."}, 0
    if state == "blocked":
        detail = _bounded_text(result.body.get("detail")) or "Run the Workspace's test command before finishing."
        if blocks >= cap:
            return (
                {"systemMessage": f"Octryx verification gate is still red after {cap} consecutive "
                 f"blocks; stopping anyway. The session stays unverified. Gate: {detail}"},
                0,
            )
        return {"decision": "block", "reason": detail}, blocks + 1
    if state == "needs_configuration":
        return (
            {"systemMessage": f"Octryx verification is not configured{_codes(result)}; "
             "this stop is not verified."},
            0,
        )
    return (
        {"systemMessage": f"Octryx verification returned an unknown state{_codes(result)}; "
         "stopping without verification."},
        0,
    )


def unread_count(result: PlatformResult) -> int | None:
    """The verification answer's ``unread_for_me``, or ``None`` when there is no usable count."""
    count = result.body.get("unread_for_me") if result.outcome == "ok" else None
    return count if type(count) is int and count >= 0 else None


def board_reminder(count: int) -> str:
    """The one reminder line: a count, never a body (worded as a friendly note)."""
    if count == 1:
        return "1 unread board message for you. Read it with board_read, then continue or stop."
    return f"{min(count, 9999)} unread board messages for you. Read them with board_read, then continue or stop."


def with_board_reminder(
    output: dict[str, Any] | None, result: PlatformResult, *, reminded: int
) -> tuple[dict[str, Any] | None, int]:
    """The unread reminder: block once per **new** unread count; returns ``(output, remembered)``.

    - A verification block carries the line in its reason (the agent reads it).
    - Otherwise the stop is blocked with the line only when the count rose above the count last reminded of;
      the same count never blocks twice, so the next stop always goes through (no loop).
    - A lower count (``board_ack``) is remembered, so a later rise blocks again. Without a usable count
      nothing changes.
    """
    count = unread_count(result)
    if count is None:
        return output, reminded
    if count == 0:
        return output, 0
    line = board_reminder(count)
    if output and output.get("decision") == "block":
        return {**output, "reason": f"{output['reason']}\n{line}"}, count
    if count > reminded:
        blocked: dict[str, Any] = {"decision": "block", "reason": line}
        if output and output.get("systemMessage"):
            blocked["systemMessage"] = output["systemMessage"]
        return blocked, count
    return output, count
