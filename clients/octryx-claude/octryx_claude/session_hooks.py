"""The prompt, compaction and session lifecycle hook commands (``hooks``): UserPromptSubmit (``/handoff`` and the
run's current contract), PreCompact/PostCompact, SessionStart and SessionEnd (the redacted digest to
``/sessions/finalize``)."""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

from octryx_claude import contract_notices

from . import pipeline, run_contract
from .digest import build_redacted_digest, transcript_inside
from .handoff_hooks import is_handoff_prompt, run_prompt_handoff, with_notice
from .hook_evidence import _remember, launcher_texts
from .hook_outputs import _bounded_text, _codes, _emit, _read_hook_input, _with_context
from .phase_brief import code_map_once, phase_brief
from .platform import SessionContext, call_control_plane, safe_code
from .seat_hooks import seat_notice
from .skills import remove_plugin
from .state import LocalState, write_private_json

FINALIZE_TIMEOUT = 25.0
PROMPT_TIMEOUT = 20.0
MAX_PROMPT_CHARS = 4000


# A plain run turn's process end is not the session's end: the turn may go on in the same session (``--resume``) when
# the platform blocks the replayed Stop. A SessionEnd finalizes the session (its presence stops, its seat credential
# is dropped), so the first process's SessionEnd would leave the resumed process with an invalid credential
# (401 ``seat_credential_invalid``). The job manager replays
# the last SessionEnd once the turn is over (``plain_driver.replay_session_end``).
DEFER_SESSION_END_ENV = "OCTRYX_DEFER_SESSION_END"
DEFERRED_SESSION_END_FILE = "deferred_session_end.json"


def _prompt_context(state: LocalState, context: SessionContext, http: httpx.Client, prompt: object) -> dict[str, Any]:
    """A Work item session or a run-bound one asks the platform at every prompt: the current run contract (a
    decision taken in the platform meanwhile), or once the first prompt's workflow proposal. Best effort."""
    if not context.work_item and run_contract.current(state, context.session_key) is None:
        return {}
    try:
        result = call_control_plane(state, context, "POST", "/sessions/prompt", http=http, timeout=PROMPT_TIMEOUT,
                                    body={"prompt": str(prompt or "")[:MAX_PROMPT_CHARS]})
    except Exception:  # noqa: BLE001 - the remembered contract stays; the next hook refreshes it
        return {}
    _remember(state, context, result)
    proposal = result.body.get("workflow_proposal") if result.outcome == "ok" else None
    return proposal if isinstance(proposal, dict) else {}


def run_user_prompt_submit(state: LocalState, http: httpx.Client) -> int:
    """``/handoff`` runs here, before any model call, and blocks the prompt; anything else passes untouched."""
    try:
        hook_input = _read_hook_input()
        prompt = hook_input.get("prompt")
        if not is_handoff_prompt(prompt):
            output = with_notice(None, seat_notice(state))  # a seat failure of the last turn, once
            context = SessionContext.from_env()
            if context is not None:
                proposal = _prompt_context(state, context, http, prompt)
                # The run's current phase for the model; a pending decision and where it is taken for the user.
                contract = run_contract.current(state, context.session_key)
                model_text, user_line = contract_notices.proposal_notice(proposal)
                output = _with_context(output, "UserPromptSubmit",
                                       run_contract.summary(contract) if contract else model_text)
                # The phase's agent, or outside a run the read-only Assistant, once per digest.
                output = _with_context(output, "UserPromptSubmit",
                                       contract_notices.agent_notice(state, context.session_key, contract))
                # The phase's compact contract, so the turn needs no workflow_run_status call.
                output = _with_context(output, "UserPromptSubmit",
                                       phase_brief(state, context.session_key, contract))
                # Where the app's files are, once per session, so the agent searches less.
                texts = launcher_texts(state, context)
                head = pipeline.text(texts, "run.launcher.code_map")
                style_head = pipeline.text(texts, "run.launcher.style_tools")  # the platform's style check
                output = _with_context(output, "UserPromptSubmit", code_map_once(
                    state, context.session_key, contract, str(hook_input.get("cwd") or ""), head, style_head))
                output = with_notice(output, run_contract.pending_notice(state, context.session_key) or user_line)
            _emit(output)
            return 0
        context = SessionContext.from_env()
        if context is None:
            _emit({"decision": "block", "reason": "Octryx handoff: no Octryx session here."})
            return 0
        _emit(run_prompt_handoff(state, context, http, prompt, hook_input.get("cwd") or "."))
    except Exception:  # noqa: BLE001 - a broken handoff must still never send /handoff to the model
        _emit({"decision": "block", "reason": "Octryx handoff failed; nothing was sent to the model."})
    return 0


CLEAR_REASON = "clear"


def _report_compaction(state: LocalState, hook_input: dict[str, Any], stage: str, http: httpx.Client) -> None:
    """The compaction as the run's event (``POST /sessions/compaction``); best effort, never in its way."""
    try:
        context = SessionContext.from_env()
        if context is None:
            return
        summary = hook_input.get("compact_summary")
        call_control_plane(state, context, "POST", "/sessions/compaction", http=http, timeout=LESSONS_TIMEOUT,
                           body={"stage": stage, "trigger": str(hook_input.get("trigger") or ""),
                                 **({"summary_chars": len(summary)} if isinstance(summary, str) else {})})
    except Exception:  # noqa: BLE001
        pass


def run_pre_compact(state: LocalState, http: httpx.Client) -> int:
    """PreCompact: the context manager's instructions for the summary (stdout); never blocks a compaction."""
    try:
        from .context_manager import pre_compact  # noqa: PLC0415

        hook_input = _read_hook_input()
        _report_compaction(state, hook_input, "pre", http)
        text = pre_compact(state, hook_input)
    except Exception:  # noqa: BLE001 - Claude Code then compacts on its own
        text = ""
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
    return 0


def run_session_start(state: LocalState, http: httpx.Client) -> int:
    """SessionStart after a compaction: the kept facts as context; anything else answers nothing."""
    try:
        from .context_manager import session_start  # noqa: PLC0415

        _emit(session_start(state, _read_hook_input()))
    except Exception:  # noqa: BLE001 - never in the way of a session start
        pass
    return 0


LESSONS_TIMEOUT = 30.0


def _send_lessons(state: LocalState, context: Any, hook_input: dict[str, Any], *, kind: str,
                  http: httpx.Client) -> None:
    """Lessons learned for the team (``session_lessons``); best effort, never in the way of the session."""
    try:
        from .session_lessons import lessons_body  # noqa: PLC0415

        body = lessons_body(state, hook_input, kind=kind)
        if body is not None:
            call_control_plane(state, context, "POST", "/sessions/lessons", http=http, timeout=LESSONS_TIMEOUT,
                               body=body)
    except Exception:  # noqa: BLE001
        pass


def run_post_compact(state: LocalState, http: httpx.Client) -> int:
    """PostCompact: Claude Code's summary plus the kept facts go to the platform as lesson material."""
    try:
        hook_input = _read_hook_input()
        _report_compaction(state, hook_input, "post", http)
        context = SessionContext.from_env()
        if context is not None:
            _send_lessons(state, context, hook_input, kind="compact", http=http)
    except Exception:  # noqa: BLE001 - never in the way of a compaction
        pass
    return 0


def run_session_end(state: LocalState, http: httpx.Client) -> int:
    try:
        hook_input = _read_hook_input()
        context = SessionContext.from_env()
        if context is None:
            return 0
        if os.environ.get(DEFER_SESSION_END_ENV) == "1":
            write_private_json(state.session_dir(context.session_key) / DEFERRED_SESSION_END_FILE, hook_input)
            return 0
        end_reason = safe_code(hook_input.get("reason")) or "other"
        if end_reason == CLEAR_REASON:
            # /clear ends a conversation, not the session: the seat credential and the presence stay
            # alive, so nothing is finalized.
            return 0
        transcript_path = str(hook_input.get("transcript_path") or "")
        # The transcript lives in the active profile's own config dir (``claude-config-seat/`` for seat).
        transcript = next(
            (found for root in (state.claude_config_dir, state.claude_config_dir_for("seat"))
             if (found := transcript_inside(transcript_path, root)) is not None),
            None,
        )
        digest = build_redacted_digest(transcript) if transcript is not None else ""
        body = {
            "end_reason": end_reason,
            "summary": f"octryx-claude session {context.session_key} ended ({end_reason}).",
            "transcript_digest": digest,
            "workspace_ref": _bounded_text(hook_input.get("cwd")),
            "claude_session_id": _bounded_text(hook_input.get("session_id")),
        }
        result = call_control_plane(
            state, context, "POST", "/sessions/finalize",
            http=http, timeout=FINALIZE_TIMEOUT, body=body,
        )
        if result.outcome != "ok" or result.state != "finalized":
            # stderr of a SessionEnd hook is shown to the user only; fixed codes only.
            sys.stderr.write(f"octryx-claude: session not finalized{_codes(result)}\n")
        remove_plugin(state, context.session_key)  # the session's catalog skills
        _send_lessons(state, context, hook_input, kind="end", http=http)  # lessons learned
    except Exception:  # noqa: BLE001 - never block session end
        sys.stderr.write("octryx-claude: session finalization failed\n")
    return 0
