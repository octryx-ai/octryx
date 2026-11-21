"""The one PreToolUse decision of a governed Claude Code session (``POST sessions/tool-check``).

The checks run in a fixed order. The first denial wins and is recorded as a ``denied_by_policy``
ToolCall:

1. **self-protection** (``self_protection.py``, code-owned): tool calls reaching for the launcher's
   credentials or the platform's control endpoints; then, for a seat analysis session only, the fixed
   analysis tool set (``analysis_tools.py``);
2. **workflow confirmation** (``confirmation.py``): ``workflow_confirm`` gets ``ask`` with a
   one-time ticket, but only with a valid hook proof; a run decision (``workflow_decide``,
   ``decision_confirmation.py``) the same way, after its node, action and payload hash were checked;
3. **Workspace tool rules** (``tool_check.py``): the Workspace policy's command and path rules; the Cedar policy
   engine evaluates the same question: compared in shadow mode, and in enforce mode a published Cedar
   policy can deny on top (``cedar_policy_denied``, the policy id as ``rule_id``);
4. **session capability** (``capability.py``): read_only unless a change workflow is confirmed, and
   changes only inside the bound repository root. On the owner's own device a ``capability_read_only`` denial
   becomes ``ask`` (the owner's chat approval confirms the change, ``devices/chat_confirmation``) when the
   Workspace's ``device_runs.chat_approvals_confirm_changes`` is on.

Anything that passes all four is ``allow``. The hook then prints nothing, so Claude Code's own
permission flow still applies.

A session bound to a **workflow run** replaces steps 4 and the selected
workflow's tool check by the run's decision (``workflow_runs/octryx/tool_policy``): the current phase's class,
tools and path rules, the run's pause or wait, no SCM or Jira client, push only in deliver. Its answer carries
the refreshed run contract (``workflow_run``).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session
from ..policy_engine.gateway_point import gateway_query
from ..policy_engine.points import POINT_GATEWAY_TOOL_CHECK
from ..policy_engine.principals import load_principal_isolated
from ..policy_engine.runtime import MODE_OFF, current_runtime, maintain_policy_runtime
from ..policy_engine.shadow import REASON_CEDAR_POLICY_DENIED, LegacyDecision, enforced_denial, shadow_decision
from ..policy_engine.workspace_facts import load_workspace_classification_isolated
from ..prompt_catalog import render_prompt
from .analysis_tools import analysis_tool_decision, review_tool_decision
from .capability import enforce_capability
from .confirmation import ask_for_confirmation, is_workflow_confirmation
from .contract import STATE_DENIED
from .decision_confirmation import ask_for_decision, is_workflow_decision
from .hook_key import launcher_state_root
from .policy import GatewayPolicy
from .self_protection import self_protection_decision
from .tool_check import ALLOW, DECISION_ALLOW, DECISION_DENY, ToolDecision, evaluate_tool_check, record_denial

logger = logging.getLogger(__name__)


async def _denied(db: AsyncSession, session: Session, hook_input: dict[str, Any], decision: ToolDecision) -> dict:
    await record_denial(db, session=session, hook_input=hook_input, decision=decision)
    run = await _announce_denial(db, session, hook_input, decision)
    from ..workflow_runs.refusal_hints import instead  # noqa: PLC0415

    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    hint = instead(run, reason=decision.reason, tool=str(hook_input.get("tool_name") or ""), tool_input=tool_input)
    payload = decision.to_payload()
    if hint:  # the concrete form this run allows, with the refusal
        payload["message"] = f"{payload['message']} {hint}".strip()
    return payload


EVENT_DENIED = "tool_denied"
MAX_DEFAULT_EVENTS = 200
EVENT_ALLOWED_BY_DEFAULT = "tool_allowed_by_default"


async def _announce_denial(db: AsyncSession, session: Session, hook_input: dict[str, Any],
                           decision: ToolDecision, *, source: str = "") -> Any:
    """Where people see a refusal and its one-click fix: the run's timeline
    (``tool_denied``, at most :data:`MAX_DEFAULT_EVENTS` per run) and the device turn's chat stream
    (``device_job_event`` ``tool_denied``, the job found by its Claude Code session, which is the gateway session
    key)."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from ...models import DeviceJob, WorkflowRunEvent  # noqa: PLC0415
    from ..knowledge.episodes.redaction import redact_episode_text  # noqa: PLC0415
    from ..workflow_runs.records import active_run_for_session, record_event  # noqa: PLC0415

    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    # The refused command or path, secrets redacted, so an event says what was refused.
    asked = str(tool_input.get("command") or tool_input.get("file_path") or "")[:300]
    detail = {"tool": str(hook_input.get("tool_name") or "unknown")[:200], "reason": decision.reason,
              "setting": (decision.remedy or {}).get("setting"), "remedy": decision.remedy,
              "message": decision.message[:1000],
              **({"input": redact_episode_text(asked).text} if asked else {}),
              **({"source": source} if source else {})}
    run = await active_run_for_session(db, session.id)
    if run is not None:
        count = (await db.execute(select(func.count()).select_from(WorkflowRunEvent).where(
            WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_DENIED))).scalar_one()
        if count < MAX_DEFAULT_EVENTS:
            record_event(db, run, EVENT_DENIED, node_id=run.current_node_id,
                         detail={**detail, "session_id": session.id})
        from ..workflow_runs.refusals import react  # noqa: PLC0415
        from ..workflow_runs.states import STATUS_RUNNING  # noqa: PLC0415

        if run.status == STATUS_RUNNING and not source:  # the phase's refusals rule (workflow data, top-10 #5)
            await react(db, run, tool=detail["tool"], reason=decision.reason, tool_input=tool_input,
                        message=decision.message)
    key = str((session.metadata_ or {}).get("gateway_session_key") or "")
    job = (await db.execute(select(DeviceJob).where(DeviceJob.claude_session_id == key).order_by(
        DeviceJob.updated_at.desc()).limit(1))).scalar_one_or_none() if key else None
    if job is None:
        return run
    from ..devices.jobs_channel import EVENT_TYPE  # noqa: PLC0415
    from ..session.stream import session_stream_manager  # noqa: PLC0415

    try:
        await session_stream_manager.publish(job.session_id, EVENT_TYPE, {
            "eventType": EVENT_DENIED, "job_id": job.id, "turn_id": job.turn_id, **detail})
    except Exception:  # noqa: BLE001 - the live view is a convenience; the run event and ToolCall row stand
        logger.warning("tool_denied_publish_failed", exc_info=True)
    return run


async def _allowed_by_default(db: AsyncSession, session: Session, hook_input: dict[str, Any],
                              decision: ToolDecision) -> dict:
    """An allow only a Workspace default gave (allow by default, block as an admin option), logged
    where people look: the run's timeline (``tool_allowed_by_default``, at most :data:`MAX_DEFAULT_EVENTS` per run),
    or the session's own count outside a run. No ToolCall row: the call's own row comes with its result."""
    from sqlalchemy import func, select  # noqa: PLC0415
    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

    from ...models import WorkflowRunEvent  # noqa: PLC0415
    from ..workflow_runs.records import active_run_for_session, record_event  # noqa: PLC0415

    tool = str(hook_input.get("tool_name") or "unknown")[:200]
    run = await active_run_for_session(db, session.id)
    if run is not None:
        count = (await db.execute(select(func.count()).select_from(WorkflowRunEvent).where(
            WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_ALLOWED_BY_DEFAULT))).scalar_one()
        if count < MAX_DEFAULT_EVENTS:
            tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
            path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")[:500]
            record_event(db, run, EVENT_ALLOWED_BY_DEFAULT, node_id=run.current_node_id,
                         detail={"tool": tool, "setting": decision.rule_id, "session_id": session.id,
                                 **({"path": path} if path else {})})
    else:
        metadata = dict(session.metadata_ or {})
        counts = dict(metadata.get(EVENT_ALLOWED_BY_DEFAULT) or {})
        if tool in counts or len(counts) < MAX_DEFAULT_EVENTS:
            counts[tool] = int(counts.get(tool) or 0) + 1
            metadata[EVENT_ALLOWED_BY_DEFAULT] = counts
            session.metadata_ = metadata
            flag_modified(session, "metadata_")
    await db.flush()
    return decision.to_payload()


async def _cedar_tool_rules(
    session: Session, policy: GatewayPolicy, hook_input: dict[str, Any], decision: ToolDecision
) -> ToolDecision:
    """The Cedar policy engine's evaluation of the tool rules.

    Shadow mode: compared and recorded, ``decision`` returned unchanged. Enforce mode: a Cedar denial of a call the
    tool rules allow becomes the answer, naming the deciding policies and the decision-log record. The principal is
    loaded in its own session, never on the request's: a failed statement there must not abort the caller's transaction.
    """
    await maintain_policy_runtime()
    if current_runtime().mode == MODE_OFF:
        return decision
    try:
        principal, records = await load_principal_isolated(session.user_id, session_id=session.id,
                                                           metadata=session.metadata_)
    except Exception:  # noqa: BLE001 - like an unavailable engine: the tool rules decide
        logger.warning("policy_engine_gateway_principal_failed", exc_info=True)
        return decision
    # The Workspace classification, resolved like the other points (own session, never raises).
    classification = await load_workspace_classification_isolated(session.project_id, session.metadata_)
    allowed = decision.decision != DECISION_DENY
    comparison = shadow_decision(
        POINT_GATEWAY_TOOL_CHECK,
        LegacyDecision(allowed, decision.rule_id or decision.reason),
        lambda: gateway_query(workspace_id=str(session.project_id or ""), gateway=policy, hook_input=hook_input,
                              principal=principal, principal_records=records, classification=classification),
    )
    denial = enforced_denial(allowed, comparison)
    if denial is None:
        return decision
    message = render_prompt("secure_work.gateway.deny.cedar_policy",
                            policy_ids=", ".join(denial.policy_ids) or "evaluation error",
                            decision_id=denial.decision_id or "unrecorded")
    return ToolDecision(DECISION_DENY, STATE_DENIED, REASON_CEDAR_POLICY_DENIED,
                        denial.policy_ids[0] if denial.policy_ids else None, message)


async def decide_tool_check(
    db: AsyncSession, *, session: Session, session_key: str, policy: GatewayPolicy, hook_input: dict[str, Any],
    grant_id: str | None = None,
) -> dict[str, Any]:
    """The tool-check answer for one PreToolUse; flushes the denial or ticket rows (the route commits)."""
    protected = self_protection_decision(hook_input, state_root=launcher_state_root(session))
    if protected is not None:
        return await _denied(db, session, hook_input, protected)
    outside_analysis = analysis_tool_decision(session, hook_input) or review_tool_decision(session, hook_input)
    if outside_analysis is not None:
        return await _denied(db, session, hook_input, outside_analysis)
    if is_workflow_confirmation(hook_input) or is_workflow_decision(hook_input):
        ask = ask_for_confirmation if is_workflow_confirmation(hook_input) else ask_for_decision
        answer = await ask(db, session=session, session_key=session_key, hook_input=hook_input)
        if answer["decision"] == DECISION_DENY:
            decision = ToolDecision(DECISION_DENY, answer["state"], answer["reason"], None, answer["message"])
            return await _denied(db, session, hook_input, decision)
        return answer
    decision = await _cedar_tool_rules(session, policy, hook_input, evaluate_tool_check(policy, hook_input))
    if decision.decision == DECISION_DENY:
        return await _denied(db, session, hook_input, decision)
    from ..workflow_runs.octryx.hooks import run_pre_tool_use

    bound = await run_pre_tool_use(db, session=session, policy=policy, hook_input=hook_input)
    if bound is not None:
        decided, contract = bound
        if decided is None:
            answer = ALLOW.to_payload()
        elif decided.decision == DECISION_ALLOW:
            answer = await _allowed_by_default(db, session, hook_input, decided)
        else:
            answer = await _denied(db, session, hook_input, decided)
        return {**answer, "workflow_run": contract}
    capability = await enforce_capability(db, session=session, session_key=session_key, hook_input=hook_input)
    if capability is not None and capability.decision == DECISION_ALLOW:
        return await _allowed_by_default(db, session, hook_input, capability)
    if capability is not None:
        # Outside a workflow run nothing turns a read-only denial into a change (a chat-confirmed
        # device edit included); changes happen only inside a workflow run.
        return await _denied(db, session, hook_input, capability)
    return ALLOW.to_payload()


__all__ = ["decide_tool_check"]
