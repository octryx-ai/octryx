"""Approval enforcement in the tool dispatch path."""

from __future__ import annotations

from typing import Any

from app.services.approval.tool_texts import gate_texts

from ...tools.context import ToolContext
from ...tools.definitions.write_risk import OUTBOUND_MESSAGE_DEFINITION_NAMES
from ...tools.outbound_message_contract import outbound_message_refusal
from ..approval import ensure_approval_request
from ..change_preview import (
    build_change_request_fingerprint,
    consume_change_preview_grant,
    record_approval_ref,
    record_enforced_approval_mark,
    upsert_change_preview,
)
from ..run_capability.chat_write_plan import is_chat_plan_write, plan_decision
from ..run_capability.chat_writes import chat_connector_write_permitted, chat_platform_write_needs_confirmation
from ..standing_approvals.argument_class import standing_rule_scope
from ..standing_approvals.tool_rules import check_standing_rule
from .previews import _chat_write_preview, _outbound_message_details, _rest_write_preview
from .rules import (
    _PER_CALL_RULES,
    RULE_CHAT_CONNECTOR_WRITE,
    RULE_CHAT_PLATFORM_WRITE,
    RULE_OUTBOUND_MESSAGE,
    ToolApprovalRequirement,
    ToolApprovalSubject,
    tool_approval_requirement,
)
from .write_kinds import (
    _is_rest_write,
    _on_device,
    device_external_write,
    external_write,
    unattended_external_write,
)


async def enforce_tool_approval(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    subject: ToolApprovalSubject | None = None,
) -> dict[str, Any] | None:
    # A granted approval is consumed for exactly this request.
    chat_write = subject is None and chat_connector_write_permitted(tool_name, context)
    chat_platform_write = subject is None and chat_platform_write_needs_confirmation(tool_name, context)
    from ..work_role_model.surfaces import trusted_writes

    if ((chat_write or chat_platform_write) and trusted_writes(context)
            and str(tool_name or "").strip() not in OUTBOUND_MESSAGE_DEFINITION_NAMES):
        # A trusted role (explicit, audited opt-in) writes without the per-call card; a tool with its
        # own approval round trip (Jira in a chat) finds the mark, as after a confirmation. An outbound message stays
        # confirmed per call.
        record_enforced_approval_mark(context, tool_name, params)
        return None
    requirement = tool_approval_requirement(tool_name, context.project_config, subject=subject,
                                            chat_connector_write=chat_write, chat_platform_write=chat_platform_write,
                                            unattended_external_write=unattended_external_write(
                                                tool_name, context, subject),
                                            device_external_write=subject is None and device_external_write(
                                                tool_name, context))
    if not requirement.required:
        return None
    if requirement.matched_rule == RULE_OUTBOUND_MESSAGE:
        # Over-limit or malformed values are refused before any preview or approval (no silent truncation).
        refusal = outbound_message_refusal(tool_name, params)
        if refusal is not None:
            return {**refusal, "blocked_by": "tool_approval_gate"}
    return await _decide_required_call(tool_name, params, context, subject=subject, requirement=requirement)


async def _decide_required_call(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    subject: ToolApprovalSubject | None,
    requirement: ToolApprovalRequirement,
) -> dict[str, Any] | None:
    # Approval identity: the explicit subject when one was supplied, otherwise the
    # dispatched tool. Both the grant lookup and the stored preview use it, so a
    # grant admits exactly the execution it was issued for.
    approval_key = requirement.subject_key or tool_name
    approval_payload = subject.payload if subject is not None and subject.payload is not None else params
    if context.db is None or not str(context.user_id or "").strip():
        return {
            "error": (
                f"Tool '{tool_name}' requires an approval, but this execution context "
                "cannot verify approvals. Execution denied."
            ),
            "tool_name": tool_name,
            "approval_subject": approval_key,
            "approval_required": True,
            "approval_status": "unverifiable",
            "blocked_by": "tool_approval_gate",
        }
    consumed: dict[str, Any] = {}
    if await consume_change_preview_grant(
        context.db,
        session_id=context.session_id,
        tool_name=approval_key,
        payload=approval_payload,
        consumed=consumed,
    ):
        # A tool with its own approval round trip (Jira in a chat) finds the mark: one call, one confirmation.
        record_enforced_approval_mark(context, tool_name, params)
        record_approval_ref(context, tool_name, params, approval_id=consumed.get("approval_id"))
        return None
    if subject is None and is_chat_plan_write(tool_name, context):
        # A chat write is admitted by the person's one confirmation of the request's write plan (one
        # confirmation per request); without a covering plan the model is told to propose or amend it, nobody is asked.
        refusal = await plan_decision(tool_name, params, context)
        if refusal is None:
            record_enforced_approval_mark(context, tool_name, params)
        return refusal
    # A Workspace's standing rule ("Always for this Workspace") answers the question for good,
    # except for an outbound message: each one is approved with its own content.
    # No standing rule for a write to an external system: a REST or connector
    # write is decided per request or per write-plan scope; a lasting exception is only the platform policy an admin
    # sets. So it is neither offered nor honoured here, even if a stored rule names it.
    standing_scope = None if external_write(tool_name, subject) else standing_rule_scope(approval_key, approval_payload)
    standing = await check_standing_rule(context.db, session_id=context.session_id, scope=standing_scope)
    if standing.covered and requirement.matched_rule not in _PER_CALL_RULES:
        record_enforced_approval_mark(context, tool_name, params)
        return None
    return await _block_pending_approval(
        tool_name, params, context, subject=subject, requirement=requirement, standing=standing
    )


async def _block_pending_approval(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    subject: ToolApprovalSubject | None,
    requirement: ToolApprovalRequirement,
    standing: Any,
) -> dict[str, Any]:
    approval_key = requirement.subject_key or tool_name
    approval_payload = subject.payload if subject is not None and subject.payload is not None else params
    approval_label = subject.display_name if subject is not None and subject.display_name else tool_name
    approval = await ensure_approval_request(
        context.db,
        requested_by=context.user_id,
        session_id=context.session_id,
        action=f"Approve tool execution for {approval_label}",
        reason=requirement.reason,
    )
    preview_payload = await _card_payload(
        tool_name, params, context, subject=subject, requirement=requirement, standing=standing,
        approval_key=approval_key, approval_payload=approval_payload,
    )
    preview = await upsert_change_preview(
        context.db,
        tool_name=approval_key,
        preview_payload=preview_payload,
        request_fingerprint=build_change_request_fingerprint(approval_key, approval_payload),
        session_id=context.session_id,
        approval_id=approval.id,
    )
    return {
        "error": "Execution blocked pending approval.",
        "tool_name": tool_name,
        "approval_subject": approval_key,
        "approval_required": True,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "change_preview_id": preview.id,
        "blocked_by": "tool_approval_gate",
    }


async def _card_payload(
    tool_name: str,
    params: dict[str, Any],
    context: ToolContext,
    *,
    subject: ToolApprovalSubject | None,
    requirement: ToolApprovalRequirement,
    standing: Any,
    approval_key: str,
    approval_payload: Any,
) -> dict[str, Any]:
    # Readable title and reasons (``approval/presentation``); the codes stay as fields.
    texts = gate_texts(tool_name, rule=requirement.matched_rule, risk=requirement.risk,
                       label=subject.display_name if subject is not None else "", on_device=_on_device(context))
    facts = list(subject.details if subject is not None else ())
    if requirement.matched_rule == RULE_OUTBOUND_MESSAGE:
        # The person approves what is sent and to whom (the grant is bound to exactly these parameters).
        facts.extend(_outbound_message_details(approval_payload))
    preview_payload = {
        "kind": "tool_execution",
        "title": texts["title"],
        "subtitle": texts["subtitle"],
        "summary": requirement.reason,
        "details": [*texts["explanation"], *facts],
        "rule": texts["rule"],
        "risk": texts["risk"],
        "toolName": tool_name,
        "approvalSubject": approval_key,
        "standing_rule": None if requirement.matched_rule in _PER_CALL_RULES else standing.scope_payload,
    }
    if requirement.matched_rule in {RULE_CHAT_CONNECTOR_WRITE, RULE_CHAT_PLATFORM_WRITE}:
        # The connector card reads every detail line as a written field: the reasons are its subtitle there.
        preview_payload = await _chat_write_preview(tool_name, params, context, {**preview_payload, "details": facts})
    elif subject is None and _is_rest_write(tool_name):
        preview_payload = await _rest_write_preview(tool_name, params, context, preview_payload)
    return preview_payload


__all__ = [
    "enforce_tool_approval",
]
