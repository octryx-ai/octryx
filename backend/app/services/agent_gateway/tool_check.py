"""PreToolUse decision for a governed client tool call (``POST sessions/tool-check``).

The launcher's PreToolUse hook sends Claude Code's raw hook input. The Workspace
policy's ``tool_rules`` are evaluated structurally (``command_match`` for Bash,
glob matching for file paths); the first matching rule denies. Every denial is
recorded on the shadow session as a ``ToolCall`` row (``source="client_hook"``,
``status="denied_by_policy"``) with a bounded, redacted copy of the tool input.
Allows are not recorded here: the model gateway already records every tool call
the model requested.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, ToolCall
from ..prompt_catalog import render_prompt
from ..redaction_policy import redact_secret_text
from .command_match import command_segments, segment_has_argument, segment_matches
from .contract import STATE_ALLOWED, STATE_DENIED, TOOL_CALL_SOURCE_HOOK, TOOL_CALL_STATUS_DENIED
from .policy import GatewayPolicy, ToolRule
from .policy_keys import (
    RULE_COMMAND_ARGUMENT_DENIED,
    RULE_COMMAND_PREFIX_DENIED,
    RULE_COMMAND_REQUIRES_ARGUMENT,
    RULE_PATH_DENIED,
)

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"

REASON_NO_RULE_MATCHED = "no_rule_matched"
REASON_TOOL_RULE_DENIED = "tool_rule_denied"
REASON_COMMAND_UNPARSEABLE = "command_unparseable"

BASH_TOOL = "Bash"
PATH_FIELDS = ("file_path", "path", "notebook_path")
COMMAND_RULE_KINDS = frozenset(
    {RULE_COMMAND_PREFIX_DENIED, RULE_COMMAND_REQUIRES_ARGUMENT, RULE_COMMAND_ARGUMENT_DENIED}
)

MAX_RECORDED_FIELDS = 20
MAX_RECORDED_FIELD_CHARS = 1000
MAX_RECORDED_COMMAND_CHARS = 2000
MAX_TOOL_NAME_CHARS = 200

# Blocking too much stops work. A call only a Workspace default lets through
# (``device_runs.tool_defaults``) is an allow with this reason, ``rule_id`` naming the setting; the run records it
# (``tool_allowed_by_default``).
REASON_ALLOWED_BY_DEFAULT = "allowed_by_default"


@dataclass(frozen=True, slots=True)
class ToolDecision:
    decision: str
    state: str
    reason: str
    rule_id: str | None = None
    message: str = ""
    # The admin's one-click fix of a denial a setting decides: ``{"setting": "device_runs.tool_defaults.<key>",
    # "value": ..., "tool": ...}`` (``POST .../tool-defaults/remedy``).
    remedy: dict[str, Any] | None = None
    # An allowed call's input as the platform corrected it (``pytest`` with ``-v``); Claude Code runs this instead.
    updated_input: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "decision": self.decision,
            "state": self.state,
            "reason": self.reason,
            "rule_id": self.rule_id,
            "message": self.message,
        }
        if self.remedy:
            payload["remedy"] = dict(self.remedy)
        if self.updated_input is not None:
            payload["updated_input"] = dict(self.updated_input)
        return payload


def allowed_by_default(setting: str, *, updated_input: dict[str, Any] | None = None) -> ToolDecision:
    """An allow that only the Workspace's default for ``setting`` (a ``tool_defaults`` key) gave."""
    return ToolDecision(DECISION_ALLOW, STATE_ALLOWED, REASON_ALLOWED_BY_DEFAULT, f"tool_defaults.{setting}",
                        updated_input=updated_input)


def setting_remedy(setting: str, value: Any, tool: str | None = None) -> dict[str, Any]:
    """The one-click fix for a denial that the Workspace's ``tool_defaults.<setting>`` decided."""
    return {"setting": f"device_runs.tool_defaults.{setting}", "value": value, **({"tool": tool} if tool else {})}


ALLOW = ToolDecision(DECISION_ALLOW, STATE_ALLOWED, REASON_NO_RULE_MATCHED)


def _deny(rule: ToolRule, tool_name: str) -> ToolDecision:
    # One catalog key per rule kind (``secure_work.gateway.deny.<kind>``).
    message = render_prompt(
        f"secure_work.gateway.deny.{rule.kind}", rule_id=rule.id, argument=rule.argument, tool=tool_name
    )
    return ToolDecision(DECISION_DENY, STATE_DENIED, REASON_TOOL_RULE_DENIED, rule.id, message)


def _command_rule_denies(rule: ToolRule, segments: list[tuple[str, ...]]) -> bool:
    for segment in segments:
        if not segment_matches(segment, rule.tokens):
            continue
        if rule.kind == RULE_COMMAND_PREFIX_DENIED:
            return True
        has_argument = segment_has_argument(segment, rule.argument)
        if rule.kind == RULE_COMMAND_REQUIRES_ARGUMENT and not has_argument:
            return True
        if rule.kind == RULE_COMMAND_ARGUMENT_DENIED and has_argument:
            return True
    return False


def candidate_paths(raw_path: str, cwd: str) -> list[str]:
    """The literal path the tool received and its normalized (absolute when possible) form."""

    literal = str(raw_path or "")
    if not literal:
        return []
    joined = literal
    if not literal.startswith(("/", "~")) and cwd.startswith("/"):
        joined = posixpath.join(cwd, literal)
    normalized = posixpath.normpath(joined)
    return list(dict.fromkeys([literal, normalized]))


def _path_rule_denies(rule: ToolRule, tool_name: str, tool_input: dict[str, Any], cwd: str) -> bool:
    if tool_name not in rule.tools:
        return False
    for field in PATH_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str) and any(fnmatchcase(path, rule.glob) for path in candidate_paths(value, cwd)):
            return True
    return False


def evaluate_tool_check(policy: GatewayPolicy, hook_input: dict[str, Any]) -> ToolDecision:
    """First matching rule denies; no match allows. Pure: no I/O."""

    tool_name = str(hook_input.get("tool_name") or "")
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    cwd = str(hook_input.get("cwd") or "")
    command_rules = [rule for rule in policy.tool_rules if rule.kind in COMMAND_RULE_KINDS]
    segments: list[tuple[str, ...]] = []
    if tool_name == BASH_TOOL and command_rules:
        parsed = command_segments(str(tool_input.get("command") or ""))
        if parsed is None:
            message = render_prompt("secure_work.gateway.unparseable_command")
            return ToolDecision(DECISION_DENY, STATE_DENIED, REASON_COMMAND_UNPARSEABLE, None, message)
        segments = parsed
    for rule in policy.tool_rules:
        if rule.kind in COMMAND_RULE_KINDS:
            if tool_name == BASH_TOOL and _command_rule_denies(rule, segments):
                return _deny(rule, tool_name)
        elif rule.kind == RULE_PATH_DENIED and _path_rule_denies(rule, tool_name, tool_input, cwd):
            return _deny(rule, tool_name)
    return ALLOW


def _recorded_input(tool_input: dict[str, Any]) -> dict[str, str]:
    recorded: dict[str, str] = {}
    for key in list(tool_input)[:MAX_RECORDED_FIELDS]:
        value = tool_input[key]
        text = value if isinstance(value, str) else json.dumps(value, default=str)[: MAX_RECORDED_FIELD_CHARS * 2]
        recorded[str(key)[:80]] = redact_secret_text(text, max_chars=MAX_RECORDED_FIELD_CHARS)
    return recorded


async def record_denial(
    db: AsyncSession,
    *,
    session: Session,
    hook_input: dict[str, Any],
    decision: ToolDecision,
) -> ToolCall:
    """One ``denied_by_policy`` ToolCall row for this denial. Flushes only."""

    tool_name = str(hook_input.get("tool_name") or "unknown")[:MAX_TOOL_NAME_CHARS]
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    parameters: dict[str, Any] = {
        "source": TOOL_CALL_SOURCE_HOOK,
        "tool_use_id": str(hook_input.get("tool_use_id") or "")[:64] or None,
        "rule_id": decision.rule_id,
        "reason": decision.reason,
        "input": _recorded_input(tool_input),
    }
    if tool_name == BASH_TOOL:
        parameters["command"] = redact_secret_text(tool_input.get("command"), max_chars=MAX_RECORDED_COMMAND_CHARS)
    row = ToolCall(
        session_id=session.id,
        tool_name=tool_name,
        parameters=parameters,
        result={"decision": decision.decision, "state": decision.state, "reason": decision.reason,
                **({"remedy": dict(decision.remedy)} if decision.remedy else {})},
        status=TOOL_CALL_STATUS_DENIED,
    )
    db.add(row)
    await db.flush()
    return row


__all__ = [
    "ALLOW",
    "DECISION_ALLOW",
    "DECISION_DENY",
    "REASON_COMMAND_UNPARSEABLE",
    "REASON_NO_RULE_MATCHED",
    "REASON_TOOL_RULE_DENIED",
    "ToolDecision",
    "candidate_paths",
    "evaluate_tool_check",
    "record_denial",
]
