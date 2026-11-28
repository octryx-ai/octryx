"""Execution policy for runtime commands: read-only refusals, server-build guard, approval grants and reviews."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...services.approval import ensure_approval_request
from ...services.change_preview import (
    build_change_request_fingerprint,
    build_command_change_preview,
    consume_change_preview_grant,
    upsert_change_preview,
)
from ...services.security_analyzer import SecurityAnalysisReport, analyze_security_risk


def _exec_policy_error_result(
    tool_name: str, command: str | list[str], analysis: SecurityAnalysisReport
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": f"Execution blocked by policy: {analysis.reason}",
        "tool_name": tool_name,
        "command": _command_text(command),
        "exec_policy_action": analysis.action,
        "exec_policy_reason": analysis.reason,
        "exec_policy_risk": analysis.risk_level,
        "security_analysis": analysis.to_dict(),
    }
    if analysis.action == "review":
        payload["approval_required"] = True
    return payload


async def _consume_approval_grant(
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
) -> bool:
    return await consume_change_preview_grant(
        context.db,
        session_id=context.session_id,
        tool_name=tool_name,
        payload={"command": command},
    )


# Tools that run a fixed, configured binary with their own read-only validation, not repository content.
_FOREIGN_BUILD_EXEMPT_TOOLS = frozenset({"run_kubectl"})


def _server_build_refusal(tool_name: str, command: str | list[str], context: ToolContext) -> dict[str, Any] | None:
    if tool_name in _FOREIGN_BUILD_EXEMPT_TOOLS:
        return None
    from ...services.execution_runtime.foreign_build_guard import guard_server_command

    return guard_server_command(command, where=f"tool:{tool_name}", audit={
        "session_id": getattr(context, "session_id", None), "user_id": getattr(context, "user_id", None)})


def _command_text(command: str | list[str]) -> str | list[str]:
    return " ".join(map(str, command)) if isinstance(command, list) else command


async def _read_only_refusal(tool_name: str, command: str | list[str], context: ToolContext) -> tuple[Any, Any]:
    from app.tools.capability_requirements import CAPABILITY_CHANGE, CAPABILITY_READ_ONLY

    from ...services.run_capability.escalation import read_only_rule_refusal
    from ...services.security_analyzer.shell_expansion import shell_expansion_refusal

    # Shell expansion is refused by capability first, judged DIRECTLY on the original string: no
    # analyzer configuration, approval grant or standing rule turns it into an execution in a
    # read-only run, since bash would run other words than the approved text.
    # Every other read-only refusal is final too —
    # no verbatim approval path in a read-only context (see ``read_only_rule_refusal``).
    expansion = shell_expansion_refusal(command) if isinstance(command, str) else None
    if expansion is not None:
        from ...services.run_capability.escalation import capability_refusal_payload

        refusal = capability_refusal_payload(
            tool_name, CAPABILITY_READ_ONLY, CAPABILITY_CHANGE, "this command", context
        )
        return {**refusal, "exec_policy_reason": f"shell expansion ({expansion})", "command": command}, None
    analysis = await analyze_security_risk(tool_name, command, context)
    hard_refusal = read_only_rule_refusal(tool_name, analysis, context)
    if hard_refusal is not None:
        return {**hard_refusal, "command": _command_text(command)}, analysis
    return None, analysis


async def _audited_server_build_refusal(
    tool_name: str, command: str | list[str], context: ToolContext
) -> dict[str, Any] | None:
    server_build = _server_build_refusal(tool_name, command, context)
    if server_build is None:
        return None
    from ...services.execution_runtime import command_audit

    try:  # the refused command's one audit row
        await command_audit.record(command, verdict="refused", where=f"tool:{tool_name}",
                                   reason=str(server_build.get("error_code") or ""))
    except command_audit.CommandAuditUnavailableError:
        pass  # refused either way
    return server_build


async def _attach_review_approval(
    result: dict[str, Any],
    *,
    tool_name: str,
    command: str | list[str],
    context: ToolContext,
    analysis: SecurityAnalysisReport,
    standing: Any,
) -> None:
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve command execution for {tool_name}",
        reason=(
            f"{analysis.reason}\nCommand: {result['command']}\nAnalyzers: {', '.join(analysis.analyzer_chain)}"
        ),
    )
    preview_payload = build_command_change_preview(
        tool_name,
        command,
        cwd=str(result.get("cwd") or ""),
    )
    preview_payload["standing_rule"] = standing.scope_payload
    change_preview = await upsert_change_preview(
        context.db,
        tool_name=tool_name,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(tool_name, {"command": command}),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    result["approval_id"] = approval.id
    result["approval_status"] = approval.status
    result["change_preview_id"] = change_preview.id
    result["change_preview"] = preview_payload


async def _exec_policy_review_result(
    tool_name: str, command: str | list[str], context: ToolContext, analysis: SecurityAnalysisReport
) -> dict[str, Any] | None:
    from ...services.standing_approvals.argument_class import command_review_scope
    from ...services.standing_approvals.tool_rules import check_standing_rule

    # A Workspace's standing rule ("Always for this Workspace") answers an exec-policy review.
    standing = await check_standing_rule(
        context.db, session_id=context.session_id, scope=command_review_scope(tool_name, command, analysis.findings)
    )
    if standing.covered:
        return None
    result = _exec_policy_error_result(tool_name, command, analysis)
    if analysis.action == "review" and context.db is not None and context.user_id:
        await _attach_review_approval(
            result, tool_name=tool_name, command=command, context=context,
            analysis=analysis, standing=standing,
        )
    return result


async def _policy_block_result(tool_name: str, command: str | list[str], context: ToolContext) -> dict[str, Any] | None:
    from app.tools.capability_requirements import CAPABILITY_READ_ONLY

    from ...services.run_capability.classes import enforced_run_capability_class

    analysis = None
    if enforced_run_capability_class(context) == CAPABILITY_READ_ONLY:
        refusal, analysis = await _read_only_refusal(tool_name, command, context)
        if refusal is not None:
            return refusal
    # Before any approval grant, standing rule or analyzer verdict: none of them turns a build on the server into an
    # execution (a read-only run has refused it above already, by capability).
    if (server_build := await _audited_server_build_refusal(tool_name, command, context)) is not None:
        return server_build
    if await _consume_approval_grant(tool_name, command, context):
        return None
    if analysis is None:
        analysis = await analyze_security_risk(tool_name, command, context)
    if analysis.action == "allow":
        return None
    from ...services.run_capability.escalation import capability_refusal_for_command

    # A governed read-only run refuses a guarded command by capability instead of
    # parking it as an approval; the turn then asks the user to allow changes.
    capability_refusal = capability_refusal_for_command(tool_name, analysis, context)
    if capability_refusal is not None:
        return {**capability_refusal, "command": _command_text(command)}
    return await _exec_policy_review_result(tool_name, command, context, analysis)
