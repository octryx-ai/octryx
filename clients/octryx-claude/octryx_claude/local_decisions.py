"""Tool decisions of an epic's story session made on the device: the hard-deny list only.

A phase whose node says ``config.tool_decisions: "local"`` (epic-delivery's story session) gets a ``local_decisions``
block in its job offer; the job manager writes it next to the session's state (:data:`POLICY_FILE`). From then on the
PreToolUse hook decides without the platform whenever it can:

- **allow**: Read / Glob / Grep / LS inside the repository; Edit / Write / MultiEdit / NotebookEdit inside the
  repository (never in ``.git`` or an environment folder) or in Claude Code's own temp folder; a Bash command that
  parses and is on no hard-deny list (``run_shell``), run from inside the repository; Claude Code's own planning tools
  (TodoWrite, Agent, …); a browser call on loopback;
- **deny**: the hard-deny list (credentials, uploads, ``rm`` outside the work folder, ``git push``, SCM and Jira
  clients), the Workspace's destructive patterns (``always_deny_patterns``), free Playwright code, a browser URL
  that is not loopback;
- **server** (a round trip to the platform) for everything else: an unparseable command, a path outside the repository,
a
  command or path a Workspace rule names (``server_commands``, ``server_path_globs``), the launcher's own state or the
  platform's control paths, the platform's MCP tools, any tool this table does not know, and any call while the run
  is not running at a free-shell phase (paused, waiting, between phases: the remembered contract says so).

A round trip per tool call costs time on every call, and so does starting the hook's Python with the whole
launcher imported. This module and ``run_shell`` import only the standard library, so the hook entry
(``octryx_claude_entry.py``) decides before the launcher's CLI is imported (:func:`fast_hook`).

What the platform still gets, without a tool call waiting for it: every local denial and every tool's execution
evidence go into a spool file (:data:`SPOOL_FILE`); the job manager uploads it in batches while the turn runs
(``POST /sessions/tool-audit``) and the Stop hook uploads the rest before the platform's verification
(:func:`drain`).
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from octryx_claude import browser_rules, local_tests_forms, local_tests_screens, local_tests_words

from . import codex_hook_input
from .local_audit_spool import (
    spool,
)
from .local_decision_rules import ALLOW, DENY, SERVER, WRITES, _bash_decision, _path_decision
from .local_policy import (
    CONTRACT_FILE,
    _read_json,
    load_policy,
    session_dir,
)

READS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead"})
# Claude Code's own tools that touch nothing outside the session (the server's READ_TOOLS without web access).
# ``claude -p`` with background subagents waits with ScheduleWakeup and Monitor. ScheduleWakeup only wakes the session;
# Monitor runs a
# shell command, so it is judged like Bash.
OWN_TOOLS = frozenset({"TodoWrite", "TodoRead", "Task", "Agent", "BashOutput", "KillShell", "KillBash", "TaskOutput",
                       "TaskStop", "ToolSearch", "ScheduleWakeup", "TaskList", "TaskGet", "TaskCreate", "TaskUpdate"})
SHELL_LIKE = frozenset({"Monitor"})


# --- the decision ---------------------------------------------------------------------------------------------------


def at_free_phase(contract: dict[str, Any] | None) -> bool:
    """The remembered run contract says: running, at a phase with a free shell and no path rules."""
    if not isinstance(contract, dict):
        return False
    run, phase = contract.get("run"), contract.get("phase")
    if not isinstance(run, dict) or run.get("status") != "running" or not isinstance(phase, dict):
        return False
    rules = phase.get("path_rules") if isinstance(phase.get("path_rules"), dict) else {}
    return phase.get("shell") == "free" and not rules.get("write") and not rules.get("protect_confirmed_tests")




# A wakeup that waits for the sandbox to let a browser start ("retry the blocked screenshot capture ... once the
# sandbox lets Chromium launch"): waiting cannot change it.
_WAITS_FOR_SANDBOX = re.compile(r"sandbox|chromium|\bchrome\b|screenshot|browser\W+(?:\w+\W+){0,3}?(?:launch|start)",
                                re.IGNORECASE)


# A run turn never sleeps on a wakeup: the session ended its turn
# with ScheduleWakeup(3600) while its frontend agent ran; ``claude -p`` aborts background agents 600 s after the main
# turn's Stop (10 of 10 interrupts on the test device), the aborted agent never sent a completion notice, and the
# process slept until the job's 60-minute limit. The agents' completion notices wake the session by themselves.
WAKEUP_IN_RUN = ("In a workflow run the platform waits for you: your agents' completion notices wake this session by "
                 "themselves, and a wakeup only keeps this turn idle. Do not schedule one; wait for your agents to "
                 "finish before you end your turn.")


def _wakeup_decision(tool_input: dict[str, Any], contract: dict[str, Any] | None = None) -> tuple[str, str, str]:

    if _WAITS_FOR_SANDBOX.search(str(tool_input.get("reason") or "")):
        return DENY, "wait_cannot_help", local_tests_screens.sandbox_browser_text(contract)
    return DENY, "wait_in_run", WAKEUP_IN_RUN


def decide(hook_input: dict[str, Any], policy: dict[str, Any] | None,
           contract: dict[str, Any] | None) -> tuple[str, str, str]:
    """``(allow | deny | server, reason, message)`` for one PreToolUse. A Codex ``apply_patch`` is decided per file
    (``codex_hook_input``): one denied file denies the patch, one the server must decide sends the patch there."""
    if not policy or not at_free_phase(contract):
        return SERVER, "", ""
    if hook_input.get("tool_name") == codex_hook_input.APPLY_PATCH:
        parts = codex_hook_input.split_apply_patch(hook_input)
        if any(part.get("tool_name") == codex_hook_input.APPLY_PATCH for part in parts):
            return SERVER, "", ""  # a patch that names no file it touches
        verdicts = [decide(part, policy, contract) for part in parts]
        return next((v for v in verdicts if v[0] == DENY), None) or next(
            (v for v in verdicts if v[0] == SERVER), None) or (ALLOW, "", "")
    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    cwd = str(hook_input.get("cwd") or "")
    if tool_name == "ScheduleWakeup":
        return _wakeup_decision(tool_input, contract)
    if tool_name in OWN_TOOLS:
        return ALLOW, "", ""
    if tool_name in READS or tool_name in WRITES:
        return _path_decision(tool_name, tool_input, cwd, policy), "", ""
    if tool_name == "Bash" or tool_name in SHELL_LIKE:
        return _bash_decision(str(tool_input.get("command") or ""), cwd, policy)
    if tool_name.startswith(browser_rules.BROWSER_TOOL_PREFIX):
        refused = browser_rules.browser_rule(tool_name, tool_input)
        return (DENY, *refused) if refused is not None else (ALLOW, "", "")
    return SERVER, "", ""


def deny_output(reason: str, message: str) -> dict[str, Any]:
    """The same answer the server's denial gives (``hooks._deny_detail``), so the model reads one format."""
    text = f"Octryx policy denied this tool call [rule local] ({reason}): {message}"
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": text[:600]}}




# --- the fast hook (before the launcher's CLI is imported) ------------------------------------------------------------


def _wrapped_test_run(hook_input: dict[str, Any], contract: dict[str, Any] | None = None) -> bool:
    """A Bash call the full hook must see: a test run it wraps or records evidence for, or the wrapper itself (also a
    run of the code style's own tools, and one the full hook refuses with the form that runs)."""
    from . import local_tests  # noqa: PLC0415 - stdlib only

    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    root = str(hook_input.get("cwd") or "")
    tools = local_tests.style_tools(contract)
    return (local_tests_words.names_wrapper(command) or local_tests.unwrap(command) is not None
            or local_tests.is_test_run(command, root, tools=tools)
            or local_tests_forms.plain_form(command, root) is not None
            or local_tests_forms.compound_system_test(command, root) is not None
            or local_tests_forms.compound_style_tool(command, root, tools) is not None)


def sandbox_note(hook_input: dict[str, Any], contract: dict[str, Any] | None = None) -> bool:
    """Tell the model once its browser failed inside the sandbox what can run instead (``local_tests``)."""

    if not local_tests_screens.sandbox_browser_failure(hook_input):
        return False
    text = local_tests_screens.sandbox_browser_text(contract)
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
    sys.stdout.flush()
    return True


# PostToolUse of these goes to the full hook: the platform's MCP tools carry its content policy.
_FULL_POST_PREFIXES = ("mcp__octryx-knowledge__",)


def fast_hook(event: str, raw: bytes) -> bool:
    """Handle ``pre-tool-use`` / ``post-tool-use`` here when the session decides locally; ``False`` hands the hook
    (with ``raw`` as its input) to the full launcher."""
    folder = session_dir()
    policy = load_policy(folder)
    if policy is None or folder is None:
        return False
    try:
        hook_input = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return False
    if not isinstance(hook_input, dict):
        return False
    tool_name = str(hook_input.get("tool_name") or "")
    if tool_name == "Bash" and _wrapped_test_run(hook_input, _read_json(folder / CONTRACT_FILE)):
        return False
    if event == "pre-tool-use" and "/tool-results/" in json.dumps(hook_input.get("tool_input")):
        return False  # possibly the session's own spilled output: the full hook reads it from a copy (spill_copy)
    if event == "post-tool-use":
        if tool_name.startswith(_FULL_POST_PREFIXES) or hook_input.get("hook_event_name") not in (
                "PostToolUse", "PostToolUseFailure"):
            return False
        for part in codex_hook_input.split_apply_patch(hook_input):
            spool(folder, "post", part)
        sandbox_note(hook_input, _read_json(folder / CONTRACT_FILE))
        return True
    if event != "pre-tool-use":
        return False
    verdict, reason, message = decide(hook_input, policy, _read_json(folder / CONTRACT_FILE))
    if verdict == SERVER:
        return False
    if verdict == DENY:
        spool(folder, "pre", hook_input, decision=DENY, reason=reason, message=message)
        sys.stdout.write(json.dumps(deny_output(reason, message)))
        sys.stdout.flush()
    return True  # allow: no output, as for the server's allow (Claude Code's own permission flow still applies)


__all__ = [
    "at_free_phase",
    "decide",
    "deny_output",
    "fast_hook",
]
