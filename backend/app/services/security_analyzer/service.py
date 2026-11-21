"""Security analyzer orchestration service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from ...tools.context import ToolContext
from .builtins import _exec_policy_analyzer, _secret_access_analyzer
from .content_command import content_command_analyzer
from .contract import (
    DEFAULT_SECURITY_ANALYZER_CHAIN,
    SecurityAnalysisReport,
    SecurityAnalyzerFinding,
    _action_rank,
    _risk_rank,
    normalize_security_analyzer_chain,
)
from .llm_risk import _llm_risk_analyzer

AnalyzerCallable = Callable[[str, str | list[str], ToolContext], Awaitable[SecurityAnalyzerFinding]]

_ANALYZER_REGISTRY: dict[str, AnalyzerCallable] = {
    "exec_policy": _exec_policy_analyzer,
    "secret_access": _secret_access_analyzer,
    "command_guardrail": content_command_analyzer,
    "llm_risk": _llm_risk_analyzer,
}


async def resolve_security_analyzer_chain(
    db: AsyncSession | None,
    *,
    project_config: Mapping[str, object] | None = None,
) -> list[str]:
    from ...services.system_config import get_agent_runtime_settings

    normalized_project_config = project_config or {}
    explicit = normalized_project_config.get("security_analyzer_chain")
    if explicit:
        return normalize_security_analyzer_chain(explicit)
    if db is None:
        return list(DEFAULT_SECURITY_ANALYZER_CHAIN)
    runtime_settings = await get_agent_runtime_settings(db)
    return normalize_security_analyzer_chain(runtime_settings.get("security_analyzer_chain"))


async def analyze_security_risk(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> SecurityAnalysisReport:
    analyzer_chain = await resolve_security_analyzer_chain(
        context.db,
        project_config=context.project_config,
    )
    from ..run_capability import CAPABILITY_READ_ONLY, enforced_run_capability_class

    if enforced_run_capability_class(context) == CAPABILITY_READ_ONLY and "exec_policy" not in analyzer_chain:
        # The read-only command rules ARE the read-only capability for commands: a configured chain may add
        # analyzers, never drop them in a read-only run.
        analyzer_chain = ["exec_policy", *analyzer_chain]
    findings: list[SecurityAnalyzerFinding] = []
    for analyzer_name in analyzer_chain:
        analyzer = _ANALYZER_REGISTRY.get(analyzer_name)
        if analyzer is None:
            continue
        findings.append(await analyzer(tool_name, command, context))

    non_allow = [finding for finding in findings if finding.action != "allow"]
    if non_allow:
        decisive = sorted(
            non_allow,
            key=lambda finding: (_action_rank(finding.action), _risk_rank(finding.risk_level)),
            reverse=True,
        )[0]
        return SecurityAnalysisReport(
            action=decisive.action,
            risk_level=decisive.risk_level,
            reason=decisive.reason,
            findings=findings,
            analyzer_chain=analyzer_chain,
        )

    if findings:
        decisive = sorted(findings, key=lambda finding: _risk_rank(finding.risk_level), reverse=True)[0]
        return SecurityAnalysisReport(
            action="allow",
            risk_level=decisive.risk_level,
            reason=decisive.reason,
            findings=findings,
            analyzer_chain=analyzer_chain,
        )

    return SecurityAnalysisReport(
        action="allow",
        risk_level="low",
        reason="No security analyzers were active for this request.",
        findings=[],
        analyzer_chain=analyzer_chain,
    )


__all__ = [
    "analyze_security_risk",
    "resolve_security_analyzer_chain",
]
