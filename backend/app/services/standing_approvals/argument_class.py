"""The scope of a standing tool approval: the tool, plus the exec-policy argument class of a command."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..security_analyzer.helpers import _command_text_and_tokens, _kubectl_verb

COMMAND_TOOLS = frozenset({"run_cli_command", "bash", "run_kubectl", "start_runtime_process"})
# The analyzers whose review a standing rule may answer: the execution policy's command rules.
STANDING_WAIVABLE_ANALYZERS = frozenset({"exec_policy"})
_SHELL_META = re.compile(r"[;&|<>`$()\\\n]")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


@dataclass(frozen=True, slots=True)
class StandingRuleScope:
    tool_name: str
    argument_class: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"tool_name": self.tool_name, "argument_class": self.argument_class}


def _token(value: str) -> str | None:
    token = str(value or "").strip().lower()
    return token if _TOKEN.match(token) else None


def command_argument_class(tool_name: str, command: Any) -> str | None:
    if not isinstance(command, (str, list)):
        return None
    text, tokens = _command_text_and_tokens(command)
    if not tokens or _SHELL_META.search(text):
        return None
    head = tokens[0].rsplit("/", 1)[-1] if tool_name == "run_kubectl" else tokens[0]
    executable = _token(head)
    if executable is None:
        return None
    if executable == "kubectl":
        verb = _token(_kubectl_verb(tokens))
        return f"kubectl {verb}" if verb else None
    if executable == "git":
        subcommand = _token(tokens[1]) if len(tokens) > 1 and not tokens[1].startswith("-") else None
        return f"git {subcommand}" if subcommand else None
    return executable


def _requested_command(tool_name: str, params: Any) -> Any:
    if not isinstance(params, dict):
        return None
    if tool_name != "run_kubectl":
        return params.get("command")
    args = params.get("args")
    if isinstance(args, str):
        return f"kubectl {args}"
    return ["kubectl", *(str(arg) for arg in args)] if isinstance(args, list) else None


def standing_rule_scope(tool_name: str, params: Any) -> StandingRuleScope | None:
    name = str(tool_name or "").strip()
    if not _TOOL_NAME.match(name):
        return None
    if name not in COMMAND_TOOLS:
        return StandingRuleScope(name)
    argument_class = command_argument_class(name, _requested_command(name, params))
    return StandingRuleScope(name, argument_class) if argument_class else None


def command_review_scope(tool_name: str, command: Any, findings: Any) -> StandingRuleScope | None:
    blocking = [finding for finding in findings or [] if getattr(finding, "action", "allow") != "allow"]
    if not blocking or not all(
        finding.action == "review" and finding.analyzer in STANDING_WAIVABLE_ANALYZERS for finding in blocking
    ):
        return None
    argument_class = command_argument_class(tool_name, command)
    return StandingRuleScope(tool_name, argument_class) if argument_class else None


def standing_rule_view(change_preview: Any) -> dict[str, Any] | None:
    preview = change_preview.get("preview") if isinstance(change_preview, dict) else None
    rule = preview.get("standing_rule") if isinstance(preview, dict) else None
    if not isinstance(rule, dict) or not valid_tool_name(rule.get("tool_name")):
        return None
    if not valid_argument_class(rule.get("argument_class")):
        return None
    return {"toolName": rule["tool_name"], "argumentClass": rule.get("argument_class")}


def valid_tool_name(value: Any) -> bool:
    return isinstance(value, str) and bool(_TOOL_NAME.match(value))


def valid_argument_class(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    parts = value.split(" ")
    return 1 <= len(parts) <= 2 and all(_TOKEN.match(part) for part in parts)


__all__ = [
    "COMMAND_TOOLS",
    "STANDING_WAIVABLE_ANALYZERS",
    "StandingRuleScope",
    "command_argument_class",
    "command_review_scope",
    "standing_rule_scope",
    "standing_rule_view",
    "valid_argument_class",
    "valid_tool_name",
]
