"""Central approval enforcement for tool dispatch.

Tool definitions declare ``approval_required`` metadata, and several connector
tools run their own approval round trip inside ``execute()``. So that a write-risk
tool without its own approval flow never simply executes, this module is an explicit,
project-policy-driven gate evaluated in the tool dispatch path.

Policy contract (the platform default plus ``project_config["approval_policy"]``, merged by
``tool_approval_policy.effective_policy``):

- ``require_for_risks``: risk levels (``write``, ``admin``) that need an approval
- ``require_for_tools``: tool names that always need an approval
- outbound messages (``write_risk.OUTBOUND_MESSAGE_DEFINITION_NAMES``) always need an approval
  bound to their exact parameters: no policy, exemption or standing rule waives it
- a connector or platform write called from a chat turn (``run_capability/chat_writes.py``) runs
  only when the request's write plan, confirmed once by the person, covers it (``run_capability/chat_write_plan.py``,
  one confirmation per request); otherwise the model is told to propose or amend the plan
  (``propose_write_plan``), whose card names every write's tool, connection and fields. No platform exemption
  and no standing rule waives it. An
  outbound message from a chat is covered the same way (its recipient is part of the plan's scope)
- a call through the ``rest_call`` device tool (Knowledge MCP, ``mcp_rest_tools``) that writes is approved per call
  by a person in the platform (rule ``device_external_write``): the device has no card to show, nobody is asked there
- ``exempt_tools``: tool names excluded from central enforcement — use this for
  tools that manage their own approval round trip (for example the cloud change
  tools), otherwise both gates would each demand an approval

Without a configured policy the gate does not require anything, which preserves
the existing behavior of self-managed approval tools. The gate reuses the same
approval + change-preview + grant mechanics as the self-managed tools, so a
granted approval resumes exactly one matching execution and is then consumed.

Callers that dispatch a *generic* tool on behalf of a more specific governed
subject — today the MCP capability paths, where both ``mcp__<server>__<tool>``
and the ``call_mcp_server_tool`` bridge address the same remote capability —
may pass a ``ToolApprovalSubject``. The subject supplies an explicit approval
identity (server + capability), an explicit risk that comes from policy metadata
instead of the generic tool definition, and the argument payload the approval is
bound to.

The dispatched tool and the subject are two *policy identities* of one request,
each carrying its own risk, and they are treated symmetrically: a rule on an
identity can only be waived by an ``exempt_tools`` entry naming that same
identity. So a subject-only exemption never waives a rule covering the dispatched
bridge tool, and an exemption naming only the dispatched tool (bridge, direct
FQN, or a tool that reaches an MCP server itself) never waives a
``require_for_tools`` or ``require_for_risks`` rule that covers the capability
subject. Every path therefore reaches the same approval decision for the same
capability and arguments, and a subject can only add reach, never remove it.
"""

from __future__ import annotations

from typing import Any

from app.services.approval.tool_texts import gate_texts

from ..tools.context import ToolContext
from ..tools.definitions.write_risk import OUTBOUND_MESSAGE_DEFINITION_NAMES
from ..tools.outbound_message_contract import outbound_message_refusal
from .approval import ensure_approval_request
from .change_preview import (
    build_change_request_fingerprint,
    consume_change_preview_grant,
    record_approval_ref,
    record_enforced_approval_mark,
    upsert_change_preview,
)
from .run_capability.chat_write_plan import is_chat_plan_write, plan_decision
from .run_capability.chat_writes import chat_connector_write_permitted, chat_platform_write_needs_confirmation
from .standing_approvals.argument_class import standing_rule_scope
from .standing_approvals.tool_rules import check_standing_rule
from .tool_approval_previews import _chat_write_preview, _outbound_message_details, _rest_write_preview
from .tool_approval_rules import (
    _PER_CALL_RULES,
    RULE_CHAT_CONNECTOR_WRITE,
    RULE_CHAT_PLATFORM_WRITE,
    RULE_OUTBOUND_MESSAGE,
    ToolApprovalRequirement,
    ToolApprovalSubject,
    tool_approval_requirement,
)
from .tool_approval_write_kinds import (
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
    """Return a blocking result when an approval is required and not granted.

    Returns ``None`` when execution may proceed: either no approval is required,
    or a matching granted approval was consumed for exactly this request.
    """
    chat_write = subject is None and chat_connector_write_permitted(tool_name, context)
    chat_platform_write = subject is None and chat_platform_write_needs_confirmation(tool_name, context)
    from .work_role_model.surfaces import trusted_writes

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
    """A call that needs an approval: a consumed grant, the chat's write plan or a standing rule admits it,
    otherwise it is blocked pending a new approval."""
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
    """Ask a person: an approval request plus the card (change preview) the grant is bound to."""
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
