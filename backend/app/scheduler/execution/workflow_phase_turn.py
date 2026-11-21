"""Prepare the first Action workflow phase through the ordinary shared turn owner."""
from __future__ import annotations

from typing import Any

from .action_admission import ActionAdmissionError


class WorkflowPhasePreparationError(ActionAdmissionError):
    def __init__(self, code: str, *, reason: str | None = None) -> None:
        super().__init__(code)
        self.reason = reason

    def as_metadata(self) -> dict[str, str]:
        result = {"code": self.code, "message": "The Action's workflow phase could not prepare its turn."}
        if self.reason:
            result["reason"] = self.reason
        return result


def _require_phase_ceiling(task: Any, resolution: dict[str, Any]) -> None:
    from ...services.run_capability.classes import capability_covers
    from ...services.run_capability.definition_contract import declared_workflow_capability
    from ...services.run_capability.schedule_capability import schedule_declared_capability

    ceiling = schedule_declared_capability(task).capability_class
    phase_class = declared_workflow_capability(resolution).capability_class
    if not capability_covers(ceiling, phase_class):
        raise WorkflowPhasePreparationError("action_workflow_capability_refused")


async def prepare_action_phase(
    db: Any, *, task: Any, session: Any, user_id: str, prompt: str,
    runtime_target_id: str | None, thinking_level: str | None,
):
    """Return shared preparation only for a declared workflow Action; never infer a phase marker.

    The callback must already have attached a runnable workflow. Execute as the session/service
    principal, retaining the Action owner solely as the run's requester. A held or missing phase
    cannot degrade to a plain prompt. This prepares one turn, never an autonomous phase loop.
    """
    from ...models import User
    from ...services.session.turn_prepare import prepare_turn_in_session
    from ...services.session.turn_refusals import TurnRefusedError
    from ...services.session.turn_request import SESSION_SCOPE_EXISTING, TurnRequest
    from ...services.workflow_runs.automation import action_run_config
    from ...services.workflow_runs.binding import run_turn_resolution
    from ...services.workflow_runs.states import RUN_RESOLUTION_KEY

    if action_run_config(task) is None:
        return None
    resolution = await run_turn_resolution(db, session, user_message=prompt)
    marker = resolution.get(RUN_RESOLUTION_KEY) if isinstance(resolution, dict) else None
    if not isinstance(marker, dict) or not marker.get("run_id"):
        raise WorkflowPhasePreparationError("action_workflow_phase_unavailable")
    if resolution.get("status") != "matched":
        raise WorkflowPhasePreparationError("action_workflow_phase_held")
    _require_phase_ceiling(task, resolution)
    user = await db.get(User, user_id)
    if user is None or not user.is_active or session.user_id != user_id:
        raise WorkflowPhasePreparationError("action_workflow_turn_refused", reason="session_access_denied")
    try:
        prepared = await prepare_turn_in_session(db, user=user, request=TurnRequest(
            user_id=user.id, session_id=session.id, session_scope=SESSION_SCOPE_EXISTING,
            prompt=prompt, project_id=task.project_id or "", project_id_explicit=True,
            agent_type="", agent_type_explicit=False,
            runtime_target_id=runtime_target_id or "", runtime_target_id_explicit=bool(runtime_target_id),
            thinking_level=thinking_level or "light", thinking_level_explicit=bool(thinking_level),
        ))
    except TurnRefusedError as exc:
        raise WorkflowPhasePreparationError("action_workflow_turn_refused", reason=str(exc.refusal.state)) from None

    from ...services.workflow_routing.workflow_selection import ROUTING_RESOLUTION_KEY

    try:
        actual = dict(session.metadata_ or {}).get(ROUTING_RESOLUTION_KEY)
        if (not isinstance(actual, dict) or actual.get("status") != "matched"
                or actual.get(RUN_RESOLUTION_KEY) != marker):
            raise WorkflowPhasePreparationError("action_workflow_phase_held")
        # Shared preparation re-resolves the run; inspect the actual recorded turn too.
        _require_phase_ceiling(task, actual)
    except WorkflowPhasePreparationError as exc:
        await settle_action_phase(db, session=session, prepared=prepared, failure_reason=exc.code)
        raise
    return prepared


async def settle_action_phase(db: Any, *, session: Any, prepared: Any, failure_reason: str | None = None) -> None:
    """Settle only this prepared turn; no completion follow-up, memory or outbound event is scheduled."""
    from ...services.session.run_state import RUN_STATUS_FAILED, set_session_run_state
    from ...services.session.turn_approval_state import CURRENT_TURN_USER_MESSAGE_KEY, end_chat_turn
    from ...services.session.turn_completion import finalize_chat_turn_after_agent_stream

    await db.refresh(session, with_for_update=True)
    metadata = dict(session.metadata_ or {})
    if metadata.get(CURRENT_TURN_USER_MESSAGE_KEY) != prepared.user_message_id:
        return  # another turn owns the session; this caller must never settle it
    if failure_reason and session.status not in {"pending_approval", "awaiting_subagents"}:
        end_chat_turn(metadata)
        session.metadata_ = metadata
        if session.status == "running":
            session.status = "active"
        set_session_run_state(session, RUN_STATUS_FAILED, failure_reason)
    else:
        # The existing finalizer preserves approval/subagent waits and guard/validation outcomes.
        # Its optional follow-up payload is deliberately ignored for this scheduled Action.
        await finalize_chat_turn_after_agent_stream(db, session_id=session.id)
    await db.commit()
