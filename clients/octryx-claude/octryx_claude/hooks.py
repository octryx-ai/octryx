"""Claude Code hook commands of an octryx session.

- ``pre-tool-use``: the platform decides (``POST /sessions/tool-check``). ``deny`` or
  any failure to get an answer denies the tool call (fail closed: model calls need the
  platform anyway). ``allow`` prints nothing, so Claude Code's normal permission flow
  still applies; printing ``permissionDecision: allow`` would skip the user's prompt. Only an ``allow`` with the
  platform's ``updated_input`` (a pytest run given ``-v``) prints it, with ``updatedInput`` (Claude Code only).
  ``ask`` (a governed ``workflow_confirm``, for example) returns
  ``permissionDecision: ask``, so the user confirms in Claude Code's own prompt. For
  ``workflow_confirm`` the hook first gets a confirmation proof from the supervisor's
  signer (fail closed without it) and passes the platform's one-time
  ``confirmation_ticket`` into the MCP call through ``updatedInput``. A run decision
  (``workflow_decide``) goes the same way with a ``decide`` proof bound to the run id; its prompt
  text is the platform's exact decision payload. In a run phase, a test run the platform allowed runs outside Claude
  Code's sandbox (``updatedInput``: the launcher's ``test-run`` wrapper, ``local_tests``) so the app can be reached
  and the device's Chrome can start; PostToolUse reports it unwrapped.
- ``stop`` (Stop and SubagentStop): the "done means verified" gate
  (``POST /sessions/verification``; Claude Code's own compaction helper is never posted,
  ``is_internal_subagent``). ``blocked`` returns ``decision: block`` with the platform's instruction,
  also when ``stop_hook_active`` is true, because the platform is the authority. To avoid an endless loop the hook
  allows the stop after ``STOP_BLOCK_CAP`` consecutive blocks of one continuation chain and says so in a
  ``systemMessage``; a chain starts again when Claude Code reports
  ``stop_hook_active: false``. ``needs_configuration`` and an unreachable platform
  allow the stop with a ``systemMessage`` (the user is never trapped).
- ``post-tool-use`` (PostToolUse and PostToolUseFailure, every tool): reports that the
  tool actually ran (``POST /sessions/tool-executed``) so the verification gate can
  tell a failed test from one refused before execution, and a workflow phase can count
  Claude Code's own reads (Read, Grep, Glob, LS) inside the repository as read evidence:
  the hook input goes unchanged, the platform derives what was read from it; a run's declared test command adds
  the JUnit report it wrote in that call (``test_report``).
  Observational: prints nothing, never blocks, always exits 0.
- ``session-end``: posts the redacted digest to ``/sessions/finalize``; always exits 0.
- a session bound to a **workflow run** (S10, ``run_contract``): PreToolUse and Stop also send the launcher's facts
  (confirmed test digests; at Stop the change), every answer's run contract is remembered, a changed contract
  reaches the model once (PostToolUse ``additionalContext``) and the user (``systemMessage``), and the prompt hook
  asks the platform for the current contract (``POST /sessions/prompt``; a session started for a Work item without
  a run gets the first prompt's workflow proposal there) and names a pending decision and where it is taken. The
  platform decides everything; the hooks only relay.
- ``stop-failure`` (seat only) and the seat steps of ``stop`` and ``user-prompt-submit``: ``seat_hooks``.
- a session whose phase decides on the device (``local_decisions``, epic-delivery): PreToolUse
  decides the hard-deny list itself and asks the platform only what it cannot decide; PostToolUse and the local
  denials go into a spool the job manager uploads in batches (``POST /sessions/tool-audit``), and Stop uploads the rest
  before the platform's verification. Most of these calls never reach this module: ``octryx_claude_entry`` answers
  them before the CLI is imported.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from octryx_claude import contract_notices, local_audit_spool

from . import hook_timings, local_decisions, mobile_summary, run_contract
from .board_hints import with_handoff_nudge
from .handoff_hooks import auto_handoff, with_notice
from .hook_evidence import (
    _remember,
    _route_notice,
    _with_facts,
)
from .hook_outputs import (
    _emit,
    _read_hook_input,
)
from .phase_brief import phase_brief
from .platform import PlatformResult, SessionContext, call_control_plane
from .seat_hooks import seat_turn_done
from .session_rules import can_read_board, is_headless, verification_notice_once
from .state import LocalState, read_json, write_private_json
from .stop_outputs import (
    STATE_NEXT_PHASE,
    _chain_key,
    is_internal_subagent,
    stop_output,
    with_board_reminder,
)

# The hook commands and the names other modules and tests use, kept on this module (``cli`` maps the events here).
__all__ = [
    "DEFERRED_STOP_FILE",
    "DEFER_STOP_ENV",
    "drain_audit",
    "run_stop",
]

VERIFICATION_TIMEOUT = 20.0
_STOP_EVENTS = {"Stop", "SubagentStop"}


def _upload_screens(state: LocalState, context: SessionContext, http: httpx.Client,
                    hook_input: dict[str, Any]) -> None:
    """The system tests' screenshots of a changing pass, for the independent review (best effort)."""
    if str(hook_input.get("hook_event_name") or "") != "Stop":
        return
    try:
        from . import screens  # noqa: PLC0415

        screens.upload(lambda body: call_control_plane(state, context, "POST", "/sessions/screenshots", http=http,
                                                       timeout=screens.TIMEOUT, body=body),
                       run_contract.current(state, context.session_key),
                       run_contract.project_root(str(hook_input.get("cwd") or "")),
                       since=screens.last_run(state.session_dir(context.session_key)))
    except Exception:  # noqa: BLE001 - screenshots are review evidence only; the Stop never depends on them
        pass


def _audit_upload(state: LocalState, context: SessionContext, http: httpx.Client, *, timeout: float):
    """The upload of a session's spooled audit events (``local_decisions.drain``); the answer's run contract is
    remembered, so a pause or a wait reaches the next tool call's local decision."""
    def post(body: dict[str, Any]) -> dict[str, Any] | None:
        result = call_control_plane(state, context, "POST", "/sessions/tool-audit", http=http, timeout=timeout,
                                    body=body, retry=True)
        if result.outcome != "ok":
            return None
        _remember(state, context, result)
        return result.body

    return post


def drain_audit(state: LocalState, context: SessionContext, http: httpx.Client, *,
                timeout: float = VERIFICATION_TIMEOUT) -> None:
    """Every spooled event to the platform before it judges the session (Stop); best effort."""
    try:
        folder = state.session_dir(context.session_key)
        # A session the platform decides for still spools the launcher's own denials (``_local_deny``).
        if local_decisions.load_policy(folder) is not None or (folder / local_audit_spool.SPOOL_FILE).exists():
            local_audit_spool.drain(folder, _audit_upload(state, context, http, timeout=timeout))
    except Exception:  # noqa: BLE001 - the verification then lacks some evidence and stays strict
        pass


DEFER_STOP_ENV = "OCTRYX_DEFER_STOP"
DEFERRED_STOP_FILE = "deferred_stop.json"
def _defer_stop(state: LocalState, context: SessionContext, hook_input: dict[str, Any]) -> bool:
    """A plain story session (``claude -p``, epic-delivery) keeps working after a Stop while its background subagents
    run: their notifications wake it again in the same process, so a Stop is not the phase's end while the process
    lives. The main session's Stop is only remembered here; the job manager replays the last one once the process has
    ended (``plain_driver``), so the platform judges the phase exactly once, after every subagent has finished."""
    if os.environ.get(DEFER_STOP_ENV) != "1" or str(hook_input.get("hook_event_name") or "") != "Stop":
        return False
    write_private_json(state.session_dir(context.session_key) / DEFERRED_STOP_FILE, hook_input)
    return True


def _stop_body(state: LocalState, context: SessionContext, http: httpx.Client,
               hook_input: dict[str, Any]) -> dict[str, Any]:
    """The verification request: the hook input with the run's facts, the mobile summary, whether the folder has
    tests at all and this launcher's capabilities; the spooled audit is drained first."""
    body = _with_facts(state, context, hook_input, with_diff=True)
    hook_timings.mark("facts")
    _upload_screens(state, context, http, hook_input)
    hook_timings.mark("screens")
    try:  # Octryx Mobile: title and last answer; never in the way of the verification
        summary = mobile_summary.stop_summary(state, hook_input)
    except Exception:  # noqa: BLE001
        summary = {}
    if summary:
        body = {**body, "mobile": summary}
    hook_timings.mark("summary")
    try:  # whether this folder has tests at all: the gate never forces a test where none can exist
        from .test_setup import has_test_setup  # noqa: PLC0415

        setup = has_test_setup(str(hook_input.get("cwd") or ""))
    except Exception:  # noqa: BLE001 - unsure: the platform decides
        setup = None
    if setup is not None:
        body = {**body, "test_setup": setup}
    body = {**body, "capabilities": [STATE_NEXT_PHASE]}  # this launcher can go on with the next phase in-turn
    hook_timings.mark("test_setup")
    drain_audit(state, context, http)  # the platform judges with every tool call's evidence
    hook_timings.mark("drain")
    return body


def _with_board_hints(state: LocalState, context: SessionContext, output: dict[str, Any] | None,
                      result: PlatformResult, *, notice: str, headless: bool) -> dict[str, Any] | None:
    """The unread board reminder and the handoff nudge, each remembered per session; a headless run hears them as a
    notice and is never blocked by them."""
    if can_read_board(state):  # never point the agent at a board its grant cannot read
        reminder_path = state.session_dir(context.session_key) / "board_reminder.json"
        reminded = read_json(reminder_path).get("count")
        reminded = reminded if type(reminded) is int else 0
        if headless:
            board, remembered = with_board_reminder(None, result, reminded=reminded)
            output = with_notice(output, (board or {}).get("reason", ""))
        else:
            output, remembered = with_board_reminder(output, result, reminded=reminded)
        write_private_json(reminder_path, {"count": remembered})
    nudge_path = state.session_dir(context.session_key) / "handoff_nudge.json"
    markers = read_json(nudge_path).get("markers")
    if not notice and can_read_board(state):  # offers and update nudges need work:manage too
        nudged = [value for value in markers if isinstance(value, str)] if isinstance(markers, list) else []
        if headless:
            nudge, markers = with_handoff_nudge(None, result, nudged=nudged)
            output = with_notice(output, (nudge or {}).get("reason", ""))
        else:
            output, markers = with_handoff_nudge(output, result, nudged=nudged)
        write_private_json(nudge_path, {"markers": markers})
    return output


def run_stop(state: LocalState, http: httpx.Client) -> int:
    try:
        hook_input = _read_hook_input()
        context = SessionContext.from_env()
        if context is not None and _defer_stop(state, context, hook_input):
            return 0
        if context is None or str(hook_input.get("hook_event_name") or "") not in _STOP_EVENTS:
            _emit(stop_output(PlatformResult("unreachable", reason="hook_context_missing"),
                              stop_hook_active=False, prior_blocks=0)[0])
            return 0
        if is_internal_subagent(hook_input):
            return 0  # Claude Code's own helper (the compaction): no part of the phase, never gated
        seat_turn_done(state)  # a completed seat turn: the subscription works again
        counter_path = state.session_dir(context.session_key) / "stop_blocks.json"
        counters = read_json(counter_path)
        key = _chain_key(hook_input)
        hook_timings.mark("started")
        body = _stop_body(state, context, http, hook_input)
        result = call_control_plane(
            state, context, "POST", "/sessions/verification",
            http=http, timeout=VERIFICATION_TIMEOUT, body=body, retry=True,
        )
        hook_timings.mark("verification", state=result.state or result.outcome)
        remembered = _remember(state, context, result)
        changed = contract_notices.changed_notice(state, context.session_key, remembered)
        output, blocks = stop_output(
            result,
            stop_hook_active=bool(hook_input.get("stop_hook_active")),
            prior_blocks=int(counters.get(key) or 0),
        )
        if result.outcome == "ok" and result.state == STATE_NEXT_PHASE and output is not None:
            # The next phase's compact contract goes with its prompt: no UserPromptSubmit runs inside the turn.
            brief = phase_brief(state, context.session_key, remembered)
            output = {**output, "reason": f"{output['reason']}\n\n{brief}".strip()}
        counters[key] = blocks
        write_private_json(counter_path, counters)
        output = verification_notice_once(state, context.session_key, output, result.state)
        headless = is_headless()  # board hints never block a headless run
        # At the handoff trigger the work is handed over once; then no handoff nudge blocks.
        notice = auto_handoff(state, context, http, result, hook_input.get("cwd") or ".")
        hook_timings.mark("handoff")
        output = _with_board_hints(state, context, output, result, notice=notice, headless=headless)
        _emit(with_notice(with_notice(with_notice(output, notice), _route_notice(state, context, result)), changed))
        hook_timings.mark("emitted")
    except Exception:  # noqa: BLE001 - never trap the user in a broken hook
        _emit({"systemMessage": "Octryx stop hook failed; stopping without verification."})
    return 0
