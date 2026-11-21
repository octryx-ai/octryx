"""Capability refusals and their escalation by explicit user decision.

A governed run that needs more capability than it has is refused at the boundary:

- tool dispatch (:func:`capability_dispatch_refusal`, wired into the registry's
  governed checks) refuses a tool whose requirement exceeds the run's class;
- the security analyzer's read-only command rules refuse a guarded shell command
  (:func:`capability_refusal_for_command`) instead of parking it as an approval.

A refusal is a dead end in chat by design. There is no "allow changes in this
session" (``escalation`` is always ``not_available``): changes happen only inside a
workflow run, and the refusal says so. ``capability_escalation_request`` answers ``None`` for every
refusal this module produces.

Exception (``chat_writes.py``): in a chat turn a connector write tool is not refused for its ``deliver``
requirement; the central approval gate asks the person to confirm that one call before it runs.
"""

from __future__ import annotations

import re
from typing import Any

from ...tools.capability_requirements import (
    CAPABILITY_CHANGE,
    CAPABILITY_DELIVER,
    CAPABILITY_READ_ONLY,
    mcp_capability_required_class,
    tool_required_capability,
)
from ..security_analyzer.contract import CAPABILITY_RULE_DETAIL_KEY
from ..workflow_contracts.decisions import (
    CAPABILITY_ESCALATION_DECISION,
    build_workflow_decision_request,
)
from .chat_writes import chat_connector_write_permitted
from .classes import capability_covers, enforced_run_capability_class, run_capability_state
from .resolution import RunCapabilityResolution

CAPABILITY_REFUSAL_KEY = "capability_refusal"
CAPABILITY_ESCALATION_METADATA_KEY = "run_capability_escalation"
CAPABILITY_REFUSAL_POLICY = "run_capability"

ESCALATION_AVAILABLE = "available"
ESCALATION_DECLINED = "declined"
ESCALATION_NOT_AVAILABLE = "not_available"

_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")


def _escalation_state(run_class: str, required: str, context: Any) -> str:
    """There is no "allow changes in chat"; changes happen only inside a workflow run."""
    return ESCALATION_NOT_AVAILABLE


def _refusal_error(run_class: str, required: str, subject: str, escalation: str) -> str:
    base = f"This run is '{run_class}'; {subject} needs '{required}' capability."
    if run_class == CAPABILITY_READ_ONLY and required == CAPABILITY_CHANGE:
        return (f"{base} Changes happen only inside a workflow run: propose feature delivery or bug fix for a "
                "Work item (or Jira intake & triage to create one) and let the user start it.")
    if escalation == ESCALATION_AVAILABLE:
        return f"{base} The user is asked whether to allow changes in this session."
    if escalation == ESCALATION_DECLINED:
        return f"{base} The user chose to stay read-only in this session; continue without changes."
    if required == CAPABILITY_DELIVER:
        return f"{base} Only a workflow that declares 'deliver' may push, open pull requests or write externally."
    return base


def capability_refusal_payload(
    tool_name: str, run_class: str, required: str, subject: str, context: Any, *, workflow_key: str = ""
) -> dict[str, Any]:
    """The closed refusal result; ``workflow_key`` names a workflow the run may not adopt."""
    escalation = _escalation_state(run_class, required, context)
    refusal = {
        "tool_name": tool_name,
        "run_capability": run_class,
        "required_capability": required,
        "escalation": escalation,
    }
    if workflow_key:
        refusal["workflow_key"] = workflow_key
    return {
        "error": _refusal_error(run_class, required, subject, escalation),
        "tool_name": tool_name,
        CAPABILITY_REFUSAL_KEY: refusal,
    }


def capability_dispatch_refusal(tool_name: str, context: Any) -> dict[str, Any] | None:
    """Refuse a tool whose requirement exceeds the run's enforced class; ``None`` allows it.

    An enforced state without a valid class (a declaration outside the closed classes) refuses
    every tool as ``needs_configuration``: it never falls back to an unenforced dispatch.
    """
    run_class = enforced_run_capability_class(context)
    state = run_capability_state(context)
    if run_class is None and state is not None and state.get("enforced") is True:
        return {
            "error": "This run's declared capability class is not configured; no tool may run until an admin sets one.",
            "status": "needs_configuration",
            "tool_name": tool_name,
            CAPABILITY_REFUSAL_KEY: {
                "tool_name": tool_name,
                "run_capability": None,
                "escalation": ESCALATION_NOT_AVAILABLE,
            },
        }
    if run_class is None:
        return None
    required = tool_required_capability(tool_name)
    if capability_covers(run_class, required):
        return None
    if chat_connector_write_permitted(tool_name, context):
        return None  # confirmed per call by the person (tool_approval_gate, chat_connector_write)
    return capability_refusal_payload(tool_name, run_class, required, f"tool '{tool_name}'", context)


def mcp_capability_dispatch_refusal(
    tool_name: str, server_name: str, capability: str, risk: str, context: Any
) -> dict[str, Any] | None:
    """Refuse a remote MCP capability whose classified risk exceeds the run's class; ``None`` allows it.

    :func:`capability_dispatch_refusal` sees only the bridge tool (a static read), so the capability's own class is
    decided here from the risk on its Workspace binding (:func:`mcp_capability_required_class`). An unclassified
    capability is not a read: a read-only run (every chat turn) uses only capabilities an admin classified ``read``.
    """
    run_class = enforced_run_capability_class(context)
    if run_class is None:
        return None
    required = mcp_capability_required_class(risk)
    if capability_covers(run_class, required):
        return None
    payload = capability_refusal_payload(
        tool_name, run_class, required, f"MCP capability '{server_name}/{capability}' (risk '{risk}')", context
    )
    if risk not in {"read", "write", "admin"}:
        payload["error"] += (" An admin can classify this capability as 'read' (risk on its Workspace capability"
                             " binding) when it only reads.")
    payload[CAPABILITY_REFUSAL_KEY]["mcp_capability"] = {"server": server_name, "tool": capability, "risk": risk}
    return payload


def capability_refusal_for_command(tool_name: str, report: Any, context: Any) -> dict[str, Any] | None:
    """Turn a security report that only the read-only command rules refused into a refusal.

    Returns ``None`` (the regular approval path applies) for unenforced runs and for
    reports where any other analyzer, or a non-capability exec-policy rule, objects.
    """
    if enforced_run_capability_class(context) != CAPABILITY_READ_ONLY:
        return None
    blocking = [finding for finding in getattr(report, "findings", []) or [] if finding.action != "allow"]
    if not blocking or not all(
        finding.analyzer == "exec_policy" and finding.action == "review"
        and (finding.details or {}).get(CAPABILITY_RULE_DETAIL_KEY) == CAPABILITY_READ_ONLY
        for finding in blocking
    ):
        return None
    payload = capability_refusal_payload(tool_name, CAPABILITY_READ_ONLY, CAPABILITY_CHANGE, "this command", context)
    payload["exec_policy_reason"] = blocking[0].reason
    return payload


def shell_expansion_capability_refusal(tool_name: str, report: Any, context: Any) -> dict[str, Any] | None:
    """In an enforced read-only run: the refusal when the read-only rules refused SHELL EXPANSION.

    An approver sees the command text (``uniq glob-*``), but bash would run other words, so no approval,
    grant or standing rule can be an informed decision about it: the refusal is final, a capability
    refusal before anything runs. A verbatim command the read-only rules refuse for
    other reasons keeps its existing approval path. ``None`` for unenforced or other runs.
    """
    if enforced_run_capability_class(context) != CAPABILITY_READ_ONLY:
        return None
    refused = [
        finding for finding in getattr(report, "findings", []) or []
        if finding.action != "allow" and finding.analyzer == "exec_policy"
        and (finding.details or {}).get(CAPABILITY_RULE_DETAIL_KEY) == CAPABILITY_READ_ONLY
        and (finding.details or {}).get("shell_expansion") is True
    ]
    if not refused:
        return None
    payload = capability_refusal_payload(tool_name, CAPABILITY_READ_ONLY, CAPABILITY_CHANGE, "this command", context)
    payload["exec_policy_reason"] = refused[0].reason
    return payload


def read_only_rule_refusal(tool_name: str, report: Any, context: Any) -> dict[str, Any] | None:
    """In an enforced read-only run: the FINAL refusal of any command the read-only command rules refuse.

    A read-only context (chat outside a workflow run, a read_only phase, a read-only programmatic origin) is
    strictly read-only. Nothing turns a read-only refusal into an execution (not even for a granted or
    approved ``sort -o out input``): no approval grant (old or
    new), standing rule or approval request. It is checked before any of them, and the read-only rules are mandatory
    in an enforced read-only chain. Includes the shell-expansion case (:func:`shell_expansion_capability_refusal`).
    ``None``
    for unenforced or other runs, and for commands the read-only rules allow (another analyzer may still ask).
    """
    if enforced_run_capability_class(context) != CAPABILITY_READ_ONLY:
        return None
    refused = [
        finding for finding in getattr(report, "findings", []) or []
        if finding.action != "allow" and finding.analyzer == "exec_policy"
        and (finding.details or {}).get(CAPABILITY_RULE_DETAIL_KEY) == CAPABILITY_READ_ONLY
    ]
    if not refused:
        return None
    payload = capability_refusal_payload(tool_name, CAPABILITY_READ_ONLY, CAPABILITY_CHANGE, "this command", context)
    payload["exec_policy_reason"] = refused[0].reason
    return payload


def _available_refusal(tool_results: list[dict[str, Any]] | None) -> tuple[str, str] | None:
    """``(tool_name, workflow_key)`` of the first escalatable refusal; unsafe names are masked."""
    for item in tool_results or []:
        result = item.get("result") if isinstance(item, dict) else None
        refusal = result.get(CAPABILITY_REFUSAL_KEY) if isinstance(result, dict) else None
        if not isinstance(refusal, dict) or refusal.get("escalation") != ESCALATION_AVAILABLE:
            continue
        if (
            refusal.get("run_capability") != CAPABILITY_READ_ONLY
            or refusal.get("required_capability") != CAPABILITY_CHANGE
        ):
            continue
        tool_name = str(refusal.get("tool_name") or "").strip()
        workflow_key = str(refusal.get("workflow_key") or "").strip()
        return (
            tool_name if _SAFE_TOOL_NAME.fullmatch(tool_name) else "tool",
            workflow_key if _SAFE_TOOL_NAME.fullmatch(workflow_key) else "",
        )
    return None


def capability_escalation_request(tool_results: list[dict[str, Any]] | None) -> tuple[str, dict[str, Any]] | None:
    """The fixed question and closed decision request for an escalatable refusal, or ``None``.

    A forged refusal marker in a tool result can at most cause this question; the
    answer itself is recorded only from the user's chat request.
    """
    refusal = _available_refusal(tool_results)
    if refusal is None:
        return None
    decision_request = build_workflow_decision_request(CAPABILITY_ESCALATION_DECISION, None)
    if decision_request is None:
        return None
    tool_name, workflow_key = refusal
    need = (
        f"the workflow `{workflow_key}` needs change capability"
        if workflow_key
        else f"the next step (`{tool_name}`) needs to change the session workspace"
    )
    message = (
        f"This session is read-only, and {need}. Choose **Allow changes in this session** to continue "
        "with change capability (edits, builds and tests in the session workspace; no push and no "
        "external writes), or **Stay read-only** to keep this session read-only."
    )
    return message, decision_request


async def record_capability_escalation(
    db: Any,
    *,
    session_metadata: dict[str, Any],
    resolution: RunCapabilityResolution,
    user_id: str | None,
    session_id: str | None,
) -> None:
    """Record and audit a change of the session's escalation decision (once per change)."""
    decision = resolution.escalation_decision or ""
    previous = session_metadata.get(CAPABILITY_ESCALATION_METADATA_KEY)
    previous_decision = previous.get("decision") if isinstance(previous, dict) else ""
    if not resolution.enforced or not decision or decision == previous_decision:
        return
    from ...models import AuditLog
    from ...time_utils import utc_now

    record = {
        "decision": decision,
        "escalated": resolution.escalated,
        "capability_class": resolution.capability_class,
        "source": resolution.source,
        "recorded_at": utc_now().isoformat(),
    }
    session_metadata[CAPABILITY_ESCALATION_METADATA_KEY] = record
    if db is not None and user_id:
        db.add(
            AuditLog(
                user_id=user_id,
                session_id=session_id or None,
                action="run_capability.escalation_decision",
                resource_type="session",
                resource_id=session_id or None,
                details={key: value for key, value in record.items() if key != "recorded_at"},
            )
        )


__all__ = [
    "CAPABILITY_ESCALATION_METADATA_KEY",
    "CAPABILITY_REFUSAL_KEY",
    "CAPABILITY_REFUSAL_POLICY",
    "ESCALATION_AVAILABLE",
    "ESCALATION_DECLINED",
    "ESCALATION_NOT_AVAILABLE",
    "capability_dispatch_refusal",
    "capability_escalation_request",
    "capability_refusal_for_command",
    "capability_refusal_payload",
    "mcp_capability_dispatch_refusal",
    "read_only_rule_refusal",
    "shell_expansion_capability_refusal",
    "record_capability_escalation",
]
