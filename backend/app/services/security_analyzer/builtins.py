"""Built-in non-LLM analyzers for command security assessment."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from app.services.security_analyzer.contract import CAPABILITY_RULE_DETAIL_KEY, SecurityAnalyzerFinding
from app.services.security_analyzer.helpers import (
    _capability_type,
    _command_text_and_tokens,
    _contains_dangerous_pattern,
)

from ...services.exec_policy import get_effective_exec_policy_config
from ...tools.context import ToolContext
from ...tools.kubernetes_kubectl_argv import kubectl_is_read_only, kubectl_subcommand
from ..agent_gateway.command_match import command_segments, writes_by_redirection
from .invocation import read_only_invocation_refusal, segment_invocation_refusal
from .read_only_git import git_read_refusal
from .read_only_options import BOUND_READ_COMMANDS
from .shell_expansion import SHELL_EXPANSION_REASONS, shell_expansion_refusal

SHELL_EXPANSION_DETAIL_KEY = "shell_expansion"


async def _exec_policy_analyzer(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> SecurityAnalyzerFinding:
    capability = _capability_type(context)
    command_text, tokens = _command_text_and_tokens(command)
    project_id = str((context.project_config or {}).get("project_id") or "").strip() or None
    config = await get_effective_exec_policy_config(context.db, project_id=project_id)
    dangerous_pattern = _contains_dangerous_pattern(command_text, config["always_deny_patterns"])
    if dangerous_pattern:
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="deny",
            risk_level="critical",
            reason="Command matches a destructive pattern blocked by execution policy.",
            details={"matched_pattern": dangerous_pattern},
        )

    if capability != "diagnosis":
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="allow",
            risk_level="normal",
            reason="Execution allowed for non-diagnosis capability.",
            details={},
        )

    finding = _diagnosis_rule_finding(tool_name, command, command_text, tokens, config)
    if finding.action == "review":
        # A read-only command rule, not a risk verdict: a governed read-only run turns
        # it into a capability refusal the user can escalate (services/run_capability).
        finding = replace(finding, details={**finding.details, CAPABILITY_RULE_DETAIL_KEY: "read_only"})
    return finding


def _shell_composition(command: str) -> str | None:
    expansion = shell_expansion_refusal(command)
    if expansion is not None:
        return expansion
    segments = command_segments(command)
    if segments is None:
        return "unparseable"
    if len(segments) != 1:
        return "compound"  # operators, pipes, newlines, background jobs, command substitutions
    if writes_by_redirection(command) is not False:
        return "redirect"
    # Assignments, wrappers and path-qualified programs change what the judged name runs (``invocation``).
    return read_only_invocation_refusal(command)


def _composed_finding(composition: str, config: dict[str, Any]) -> SecurityAnalyzerFinding:
    return SecurityAnalyzerFinding(
        analyzer="exec_policy",
        action="review",
        risk_level="medium",
        reason="Diagnosis mode blocks compound or redirecting shell commands without explicit approval.",
        details={
            "composition": composition,
            "operators": list(config["shell_risk_operators"]),
            # The text bash would expand into other words than the ones shown (``shell_expansion``).
            SHELL_EXPANSION_DETAIL_KEY: composition in SHELL_EXPANSION_REASONS,
        },
    )


def _kubectl_rule_args(tool_name: str, tokens: list[str]) -> list[str]:
    args = list(tokens[1:])
    if tool_name == "run_kubectl":
        while len(args) >= 2 and args[0] in ("--kubeconfig", "--context", "-n"):
            args = args[2:]
    return args


def _diagnosis_rule_finding(
    tool_name: str,
    command: str | list[str],
    command_text: str,
    tokens: list[str],
    config: dict[str, Any],
    *,
    kubectl_context_selectable: bool = False,
) -> SecurityAnalyzerFinding:
    shell = isinstance(command, str)
    composition = _shell_composition(command) if shell else None
    operator = shell and any(item in command_text for item in config["shell_risk_operators"])
    if composition is not None or operator:
        return _composed_finding(composition or "operator", config)

    if tool_name == "run_kubectl" or (tokens and tokens[0].rsplit("/", 1)[-1] == "kubectl"):
        args = _kubectl_rule_args(tool_name, tokens)
        verb = kubectl_subcommand(args)
        # The configured verbs can narrow the read-only kubectl decision, never widen it to a write.
        read_only = kubectl_is_read_only(args, context_selectable=kubectl_context_selectable)
        if verb in set(config["diagnosis_kubectl_verbs"]) and read_only:
            return SecurityAnalyzerFinding(
                analyzer="exec_policy",
                action="allow",
                risk_level="low",
                reason="Read-only kubectl verb allowed in diagnosis mode.",
                details={"verb": verb},
            )
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="review",
            risk_level="medium",
            reason="Diagnosis mode only allows read-only kubectl verbs without approval.",
            details={"verb": verb},
        )
    if not shell:
        # An argv list runs without a shell: operator tokens are literal arguments, but the invocation and
        # option rules hold exactly as for a string (``['find', '.', '-delete']``, ``['uniq', 'in', 'out']``).
        reason = segment_invocation_refusal(tokens)
        if reason is not None:
            return SecurityAnalyzerFinding(
                analyzer="exec_policy",
                action="review",
                risk_level="medium",
                reason="Diagnosis mode admits only plain read commands with their reading options.",
                details={"invocation": reason},
            )

    primary = tokens[0].lower() if tokens else ""
    if primary in set(config["diagnosis_read_only_commands"]) and primary not in BOUND_READ_COMMANDS:
        # A configured read command without a closed option table could write or execute: fail closed.
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="review",
            risk_level="medium",
            reason="Diagnosis mode admits only read commands with a closed option binding.",
            details={"primary": primary},
        )
    if primary in set(config["diagnosis_read_only_commands"]):
        if primary == "sed" and any(token == "-i" or token.startswith("-i") for token in tokens[1:]):
            return SecurityAnalyzerFinding(
                analyzer="exec_policy",
                action="review",
                risk_level="medium",
                reason="In-place file editing is not allowed in diagnosis mode without approval.",
                details={"primary": primary},
            )
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="allow",
            risk_level="low",
            reason="Read-only shell command allowed in diagnosis mode.",
            details={"primary": primary},
        )

    if primary == "git":
        subcommand = tokens[1].lower() if len(tokens) > 1 else ""
        # An admitted subcommand name is not enough — the whole git invocation
        # must be a closed read form (global options, the subcommand's option table, operand rules).
        if git_read_refusal(tokens[1:], config["diagnosis_git_subcommands"]) is None:
            return SecurityAnalyzerFinding(
                analyzer="exec_policy",
                action="allow",
                risk_level="low",
                reason="Read-only git command allowed in diagnosis mode.",
                details={"subcommand": subcommand},
            )
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="review",
            risk_level="medium",
            reason="Diagnosis mode only allows read-only git commands without approval.",
            details={"subcommand": subcommand},
        )

    # Every command that is not recognized as read-only needs approval; there is no separate review list.
    if primary:
        return SecurityAnalyzerFinding(
            analyzer="exec_policy",
            action="review",
            risk_level="medium",
            reason="Diagnosis mode requires approval for commands that are not recognized as read-only.",
            details={"primary": primary},
        )

    return SecurityAnalyzerFinding(
        analyzer="exec_policy",
        action="review",
        risk_level="medium",
        reason="Command could not be classified safely in diagnosis mode.",
        details={},
    )


def read_only_command_finding(
    command: str, config: dict[str, Any], *, kubectl_context_selectable: bool = False
) -> SecurityAnalyzerFinding:
    command_text, tokens = _command_text_and_tokens(command)
    # A shell command string: composition first, then kubectl's read-only rules or the command rules.
    return _diagnosis_rule_finding("run_cli_command", command, command_text, tokens, config,
                                   kubectl_context_selectable=kubectl_context_selectable)


_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"(?i)\b(?:env|printenv)\b(?:\s|$)",
        "review",
        "Environment dump commands should be reviewed because they can expose secrets.",
    ),
    (
        r"(?i)\b(?:cat|less|more|head|tail|sed|grep)\b.+(?:\.env(?:\.[A-Za-z0-9_-]+)?|id_rsa|id_dsa|id_ed25519|\.pem|\.kube/config)\b",
        "review",
        "Secret-bearing files should not be read without review.",
    ),
    (
        r"(?i)\bkubectl\b.+\b(?:get|describe)\b.+\bsecret(?:s)?\b",
        "review",
        "Direct secret reads from Kubernetes should be reviewed.",
    ),
    (
        r"(?i)\baws\s+ssm\s+get-parameter\b.+--with-decryption\b",
        "review",
        "Decrypting SSM parameters should be reviewed.",
    ),
    (
        r"(?i)\bvault\s+(?:read|kv\s+get)\b",
        "review",
        "Vault secret reads should be reviewed.",
    ),
]


async def _secret_access_analyzer(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> SecurityAnalyzerFinding:
    command_text, _ = _command_text_and_tokens(command)
    for pattern, action, reason in _SECRET_PATTERNS:
        match = re.search(pattern, command_text, flags=re.IGNORECASE)
        if not match:
            continue
        return SecurityAnalyzerFinding(
            analyzer="secret_access",
            action=action,
            risk_level="high",
            reason=reason,
            details={"matched_excerpt": match.group(0)[:200], "tool_name": tool_name},
        )
    return SecurityAnalyzerFinding(
        analyzer="secret_access",
        action="allow",
        risk_level="low",
        reason="No obvious secret access pattern detected.",
        details={},
    )
