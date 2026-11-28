"""Low-level parsing and scoring helpers used by security analyzers."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

from ...tools.context import ToolContext


def _capability_type(context: ToolContext) -> str:
    from ..run_capability import enforced_run_capability_class, guardrail_capability_type

    return guardrail_capability_type(enforced_run_capability_class(context) or "")


def _contains_dangerous_pattern(command_text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, command_text, flags=re.IGNORECASE):
            return pattern
    return None


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.strip().split()


_KUBECTL_FLAGS_WITH_VALUE = frozenset({
    "--as",
    "--as-group",
    "--cluster",
    "--context",
    "--kubeconfig",
    "--namespace",
    "--request-timeout",
    "--server",
    "--token",
    "--user",
    "-n",
})


def _kubectl_subcommand_args(tokens: list[str]) -> list[str]:
    skip_next = False
    for index, token in enumerate(tokens[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if token in _KUBECTL_FLAGS_WITH_VALUE:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return tokens[index:]
    return []


def _kubectl_verb(tokens: list[str]) -> str:
    args = _kubectl_subcommand_args(tokens)
    return args[0] if args else ""


def _command_text_and_tokens(command: str | list[str]) -> tuple[str, list[str]]:
    if isinstance(command, list):
        return " ".join(str(part) for part in command), [str(part) for part in command]
    text = str(command or "").strip()
    return text, _shell_tokens(text)


def _extract_json_object(payload: str) -> dict[str, Any]:
    text = str(payload or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _score_to_action(*, score: int, review_threshold: int, deny_threshold: int) -> str:
    if score >= deny_threshold:
        return "deny"
    if score >= review_threshold:
        return "review"
    return "allow"


def _score_to_risk_level(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"
