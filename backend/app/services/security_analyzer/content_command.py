"""Command safety's ``command_guardrail`` check: content handling of the kinds that matter for commands.

The command text is scanned with the detectors of the commands-relevant kinds (``content_security.handling``:
credentials, credential assignments, internal IP addresses) the Workspace's plan acts on (surface ``commands``).
Per kind found, the plan's action decides:

- shipped default ``review`` (and ``mask``: a command cannot be masked): sent for review, because the value would
  leave the platform in the command's output or arguments;
- ``refuse``: denied;
- ``reroute`` / ``mask_reroute``: denied with ``content_route_unavailable`` (a command cannot be rerouted);
- ``report``: allowed, the finding named as informational.

Email addresses are not a reason to ask a person (``git config user.email``), prompt-injection phrases are a
model-input concern. The finding names the policies and detector counts, never the matched text. A command the
scan could not finish examining (``Examination.finished`` false) is sent for review: no finding is not the same as
a clean command. A plan that cannot be read denies (``content_handling_unavailable``).
"""

from __future__ import annotations

from ...tools.context import ToolContext
from ..content_detection.examination import DISPOSITION_ALLOW, DISPOSITION_REVIEW, examine_text
from ..content_detection.scanner import DetectorSet
from ..content_security.handling import (
    ACTION_MASK,
    ACTION_REFUSE,
    ACTION_REPORT,
    ACTION_REVIEW,
    PLATFORM_SESSION_WITHOUT_WORKSPACE,
    REASON_HANDLING_UNAVAILABLE,
    REASON_ROUTE_UNAVAILABLE,
    REROUTING,
    SURFACE_COMMANDS,
    ContentHandlingUnavailableError,
    PlatformScope,
    content_handling_isolated,
)
from .contract import SecurityAnalyzerFinding
from .helpers import _command_text_and_tokens

ANALYZER = "command_guardrail"
SOURCE_COMMAND = "command"


def _scope(context: ToolContext | None) -> str | PlatformScope:
    """The turn's Workspace, or — a turn without one is a session without a Workspace by design — the platform
    scope (``handling.PlatformScope``)."""
    config = context.project_config if context is not None and isinstance(context.project_config, dict) else {}
    chosen = config.get("project_id") or (context.project_ids[0] if context is not None and context.project_ids
                                          else None)
    return str(chosen) if chosen else PlatformScope(PLATFORM_SESSION_WITHOUT_WORKSPACE)


async def content_command_analyzer(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> SecurityAnalyzerFinding:
    try:
        plan = await content_handling_isolated(_scope(context), SURFACE_COMMANDS)
    except ContentHandlingUnavailableError:
        return SecurityAnalyzerFinding(analyzer=ANALYZER, action="deny", risk_level="high",
                                       reason="The Workspace's content handling cannot be read.",
                                       details={"reason": REASON_HANDLING_UNAVAILABLE, "tool_name": tool_name})
    command_text, _ = _command_text_and_tokens(command)
    examination = examine_text(command_text, SOURCE_COMMAND, DetectorSet(builtin=plan.acting))
    detected = examination.detected
    acting = plan.policies(detected, ACTION_REVIEW, ACTION_MASK, ACTION_REFUSE, *REROUTING)
    if examination.disposition(allowed=not acting, incomplete=DISPOSITION_REVIEW) == DISPOSITION_ALLOW:
        informational = plan.policies(detected, ACTION_REPORT)
        details = {"informational": list(informational), "found": examination.report.counts()} if informational \
            else {}
        return SecurityAnalyzerFinding(analyzer=ANALYZER, action="allow", risk_level="low",
                                       reason="No content handling stops the command.", details=details)
    if not examination.finished:
        return SecurityAnalyzerFinding(
            analyzer=ANALYZER, action="review", risk_level="high",
            reason="The command is too large or dense to check against the content handling.",
            details={"unfinished": True, "tool_name": tool_name})
    details = {"policies": list(acting), "found": examination.report.counts(), "tool_name": tool_name}
    refused = plan.policies(detected, ACTION_REFUSE)
    rerouted = plan.policies(detected, *REROUTING)
    if refused or rerouted:
        reason = REASON_ROUTE_UNAVAILABLE if rerouted and not refused else "content_policy_denied"
        return SecurityAnalyzerFinding(analyzer=ANALYZER, action="deny", risk_level="high",
                                       reason=f"Content handling {', '.join(refused or rerouted)} refuses the "
                                              "command input.", details={**details, "reason": reason})
    return SecurityAnalyzerFinding(
        analyzer=ANALYZER,
        action="review",
        risk_level="high",
        reason=f"Content policy {', '.join(acting)} matched the command input.",
        details=details,
    )


__all__ = ["content_command_analyzer"]
