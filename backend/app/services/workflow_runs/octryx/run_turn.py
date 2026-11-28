"""Start one of a run's own device turns with its settings and the seat's fallbacks to the governed profile."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, WorkflowRun
from ..graph import PhasedNode
from ..records import main_session_id, record_event
from ..states import STATUS_RUNNING
from .continuation_marker import _device_target, _parse_time
from .turn_settings import _with_run_settings

REASON_SEAT_NEEDS_GOVERNED = "content_requires_governed"
EVENT_PROFILE_GOVERNED = "runtime_profile_governed"


# Refusals of the seat that the governed profile does not have (defaults must let the work
# run): the sensitive-content opt-in and the Workspace's seat decision (agent_gateway.seat_policy_keys). A workflow
# run then continues governed on the same device and folder, with one event saying why.
_SEAT_FALLBACK_MESSAGES = {
    REASON_SEAT_NEEDS_GOVERNED: "The conversation contains personal or sensitive data, so your own seat may not "
                                "process it.",
    "seat_mode_forbidden": "This Workspace does not allow your own seat.",
    "seat_requires_governed_routing": "This Workspace routes every call through the platform's models.",
    "seat_classification_too_sensitive": "The Workspace's data classification does not allow your own seat.",
    "seat_classification_unresolved": "The Workspace has no data classification yet, so your own seat is not allowed.",
    "seat_classification_requires_governed_routing": "The Workspace's data classification needs the platform's "
                                                     "models.",
}
SEAT_FALLBACK_REASONS = frozenset(_SEAT_FALLBACK_MESSAGES)


async def _switch_to_governed(db: AsyncSession, run: WorkflowRun, thread: Session, *, node_id: str,
                              reason: str = REASON_SEAT_NEEDS_GOVERNED, limit: Any = None,
                              engine: str = "") -> dict[str, Any]:
    from ..runtime_target.target import apply_to_thread, stored_target, with_target
    from .seat_fallback import FALLBACK_KEY, remember_fallback

    previous = stored_target(run) or {**dict(_device_target(thread) or {}), "kind": "device"}
    governed = {**previous, "profile": "governed"}
    run.context = with_target(run.context, governed, actor_id=None)
    apply_to_thread(thread, governed)
    until: dict[str, Any] = {}
    if limit is not None:
        remember_fallback(run, until=limit.until, reset_known=limit.reset_known, engine=engine, reason=reason)
        until = {"until": dict(run.context or {})[FALLBACK_KEY]["until"], "reset_known": limit.reset_known,
                 "engine": engine, "said": limit.said}
    back = (f" It returns to your seat after the reset ({until['until']})." if until.get("reset_known")
            else " Your seat is tried again in an hour." if until else "")
    record_event(db, run, EVENT_PROFILE_GOVERNED, node_id=node_id, detail={
        "reason": reason, "from": previous.get("profile"), "to": "governed", **until,
        "message": f"{_SEAT_FALLBACK_MESSAGES.get(reason, 'Your own seat may not take this step.')} "
                   f"The run continues on the same device with the platform's governed models.{back}"})
    return {**dict(_device_target(thread) or {})}


async def _return_to_seat(db: AsyncSession, run: WorkflowRun, thread: Session, *, node_id: str) -> dict[str, Any]:
    from ..runtime_target.target import apply_to_thread, stored_target, with_target
    from .seat_fallback import EVENT_SEAT_RETURNED, clear_fallback

    seat = {**(stored_target(run) or {**dict(_device_target(thread) or {}), "kind": "device"}), "profile": "seat"}
    run.context = with_target(run.context, seat, actor_id=None)
    state = clear_fallback(run) or {}
    apply_to_thread(thread, seat)
    main_id = await main_session_id(db, run)
    if main_id and main_id != thread.id:
        apply_to_thread(await db.get(Session, main_id), seat)
    record_event(db, run, EVENT_SEAT_RETURNED, node_id=node_id, detail={
        "reset_at": state.get("until"), "reset_known": bool(state.get("reset_known")), "engine": state.get("engine"),
        "message": "The seat's usage limit has reset: the run continues on your own seat."})
    return {**dict(_device_target(thread) or {})}


async def start_run_turn(db: AsyncSession, run: WorkflowRun, node: PhasedNode, thread: Session,
                         target: dict[str, Any], start: Any, *, suffix: str = "",
                         model: str = "") -> tuple[Any, dict[str, Any]]:
    from ...devices.chat_turn import DeviceTurnStarted
    from ..runtime_target.seat_required import pause_for_seat, seat_on_pool
    from .seat_fallback import fallback_state, reset_passed

    if seat_on_pool(target):
        return await pause_for_seat(db, run), target
    company_model = ""  # the same-class company model while the seat is at its limit: it wins over every other

    async def settings(target: dict[str, Any]) -> dict[str, Any]:
        target = await _with_run_settings(db, run, node, target, thread.user_id)
        chosen = company_model if target.get("profile") == "governed" and company_model else model
        return {**target, "model": chosen} if chosen else target

    if target.get("profile") == "governed" and fallback_state(run) is not None and reset_passed(run):
        # On the company models only because the seat was at its limit, and that limit has reset.
        target = await _return_to_seat(db, run, thread, node_id=node.id)
    if target.get("profile") == "seat" and target.get("device_id"):
        from ...devices.seat_quota import seat_limit
        from ..review.choice import run_engine
        from ..runtime_target.target import stored_target

        chosen = _parse_time(str(dict(stored_target(run) or {}).get("at") or ""))
        engine = await run_engine(db, run)
        limit = await seat_limit(db, str(target["device_id"]), engine=engine, chosen_at=chosen)
        if limit is not None:
            # The seat answered with its usage limit and has not reset yet: never start a turn only to see it fail.
            target = await _switch_to_governed(db, run, thread, node_id=node.id, reason=REASON_SEAT_LIMIT,
                                               limit=limit, engine=engine)
    if target.get("profile") == "governed" and fallback_state(run) is not None:
        chosen_model = await _same_class_company_model(db, run, node, thread, target, settings)
        if chosen_model is None:
            return await _pause_without_same_class(db, run, node, target, settings), target
        company_model = chosen_model

    async def start_with_model_fallback(target: dict[str, Any], suffix: str) -> tuple[Any, dict[str, Any]]:
        started = await start(target, suffix)
        if not isinstance(started, DeviceTurnStarted) and started.reason == "device_model_not_allowed" \
                and target.get("model"):
            # The Workspace does not admit the chosen run model for this profile: the device's default instead.
            record_event(db, run, "run_turn_model_refused", node_id=node.id,
                         detail={"model": target["model"], "profile": target.get("profile")})
            target = {**target, "model": ""}
            started = await start(target, f"{suffix}:d")
        return started, target

    started, target = await start_with_model_fallback(await settings(target), suffix)
    if not isinstance(started, DeviceTurnStarted) and started.reason in SEAT_FALLBACK_REASONS \
            and target.get("profile") == "seat":
        # The seat may not take it (sensitive content or the Workspace's seat decision); governed may (device_policy).
        # The run keeps going on the same device and folder with the governed profile instead of stopping silently.
        target = await _switch_to_governed(db, run, thread, node_id=node.id, reason=started.reason)
        started, target = await start_with_model_fallback(await settings(target), f"{suffix}:g")
    return started, target


async def _same_class_company_model(db: AsyncSession, run: WorkflowRun, node: PhasedNode, thread: Session,
                                    target: dict[str, Any], settings: Any) -> str | None:
    # None: the Workspace admits no company alias of that class, and the run must not run on a bigger one.
    from .seat_fallback import (
        EVENT_FALLBACK_MODEL,
        admitted_company_aliases,
        model_class,
        note_fallback_model,
        same_class_alias,
    )
    from .seat_models import chose_class_default

    seat_model = str((await settings({**target, "profile": "seat"})).get("model") or "")
    if model_class(seat_model) is None or chose_class_default(run, node.id):
        return ""  # a class default is nobody's choice: the governed profile's own model, as for the device default
    entries = await admitted_company_aliases(db, user_id=str(thread.user_id), workspace_id=str(run.project_id or ""),
                                             device_id=str(target.get("device_id") or ""))
    alias = same_class_alias(entries, seat_model)
    if alias is not None and note_fallback_model(run, seat_model, alias):
        until = dict(dict(run.context or {}).get("seat_fallback") or {}).get("until")
        record_event(db, run, EVENT_FALLBACK_MODEL, node_id=node.id, detail={
            "seat_model": seat_model, "company_model": alias, "class": model_class(seat_model), "until": until,
            "message": f"Company model {alias} instead of {seat_model} (same class) until {until}."})
    return alias


async def _pause_without_same_class(db: AsyncSession, run: WorkflowRun, node: PhasedNode, target: dict[str, Any],
                                    settings: Any) -> Any:
    from ...devices.chat_turn import DeviceTurnRefusal
    from ..limits import pause_run
    from ..states import PAUSE_RUNTIME_FAILED
    from .seat_fallback import REASON_NO_SAME_CLASS, fallback_state, model_class

    state = fallback_state(run) or {}
    seat_model = str((await settings({**target, "profile": "seat"})).get("model") or "")
    until, known = state.get("until"), bool(state.get("reset_known"))
    if run.status == STATUS_RUNNING:
        await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
            "code": REASON_NO_SAME_CLASS, "seat_model": seat_model, "class": model_class(seat_model),
            "reset_at": until, "reset_known": known, "engine": state.get("engine"),
            "message": (f"Your seat is at its usage limit until {until}"
                        f"{'' if known else ' (reset not named; tried again then)'}, and this Workspace admits no "
                        f"company model of the same class as {seat_model}. Continue after the reset, admit a "
                        f"{model_class(seat_model)}-class company model, or abort the run."),
            "resume": {"kind": "restart", "node_id": run.current_node_id},
        })
    return DeviceTurnRefusal(state="denied", reason=REASON_NO_SAME_CLASS, status=409)


REASON_SEAT_LIMIT = "seat_usage_limit"
_SEAT_FALLBACK_MESSAGES[REASON_SEAT_LIMIT] = "Your own seat (subscription) reached its usage limit."
