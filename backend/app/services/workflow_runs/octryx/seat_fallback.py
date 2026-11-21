"""A run on a seat at its usage limit: the company model of the same class, and back to the seat after the reset.

The rules (a run must neither get stuck nor flap when a person's subscription is used up):

- **same class**: while the seat (Claude Code or Codex on the person's own login) is at its limit, the run's turns run
  on the governed profile with an admitted company alias of the *same class* as the seat model the turn would have
  used (sonnet → a sonnet-class alias, sol → a sol-class Codex alias), never a bigger one. When the Workspace admits
  none, the run pauses (:data:`REASON_NO_SAME_CLASS`) with the seat model and the reset in the pause. A turn whose
  seat model is unknown (the device's default) keeps the governed profile's own choice;
- **back to the seat**: the switch is remembered in ``run.context[`` :data:`FALLBACK_KEY` ``]`` with the reset; the
  first turn after it runs on the seat again (event :data:`EVENT_SEAT_RETURNED`). A reset the account did not name
  is the report plus ``seat_quota.UNKNOWN_RESET``: the seat is tried again then, and falls back again if it is still
  at its limit;
- **visible and budgeted**: the switch (``runtime_profile_governed``), the company model chosen
  (:data:`EVENT_FALLBACK_MODEL`) and the return are run events (the board's run view and the phone's watch view read
  them, ``attention.event_text``); :func:`fallback_view` is the run view's "on company fallback until <reset>". The
  company calls run on the same run-bound thread, so the gateway meters them against the run's budget like any other
  call (``model_gateway.inbound.run_limits`` → ``model_guard.guard_model_call``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....time_utils import utc_now
from .model_guard import codex_tier, model_tier

FALLBACK_KEY = "seat_fallback"
EVENT_SEAT_RETURNED = "seat_returned"
EVENT_FALLBACK_MODEL = "seat_fallback_model"
REASON_NO_SAME_CLASS = "seat_limited_no_same_class_fallback"
_CLAUDE_CLASSES = ("haiku", "sonnet", "opus")
_CODEX_CLASSES = ("luna", "terra", "sol", "astra")


def model_class(model: str) -> str | None:
    """A model's class word (``sonnet``, ``sol`` …), Codex's only for a Codex model; ``None`` when unknown."""
    name = str(model or "").lower()
    if codex_tier(name) is not None or "gpt-" in name:
        return next((word for word in _CODEX_CLASSES if word in name), None)
    if model_tier(name) is not None:
        return next((word for word in _CLAUDE_CLASSES if word in name), None)
    return None


def _codex(model: str) -> bool:
    return "gpt-" in str(model or "").lower()


def alias_class(entry: Any) -> str | None:
    """A company alias's class from its name, display name, model group or served model ids (first that names one)."""
    names = [str(getattr(entry, key, "") or "") for key in ("alias", "display_name", "model_group")]
    names += sorted(str(item) for item in getattr(entry, "served_model_ids", ()) or ())
    codex = any(_codex(name) for name in names)
    for name in names:
        word = next((word for word in (_CODEX_CLASSES if codex else _CLAUDE_CLASSES) if word in name.lower()), None)
        if word is not None:
            return word
    return None


def same_class_alias(entries: Any, seat_model: str) -> str | None:
    """The first admitted alias of ``seat_model``'s class (and family: a Codex seat never gets a Claude alias)."""
    wanted = model_class(seat_model)
    if wanted is None:
        return None
    for entry in entries:
        names = [str(getattr(entry, key, "") or "") for key in ("alias", "display_name", "model_group")]
        names += [str(item) for item in getattr(entry, "served_model_ids", ()) or ()]
        if any(_codex(name) for name in names) == _codex(seat_model) and alias_class(entry) == wanted:
            return str(entry.alias)
    return None


async def admitted_company_aliases(db: AsyncSession, *, user_id: str, workspace_id: str, device_id: str) -> tuple:
    """The company aliases the governed profile of this device job admits (``devices.device_models``)."""
    from ...devices.contract import DEVICE_POLICY_CLIENT
    from ...model_gateway.inbound.admission import admitted_tool_aliases
    from ...policy_engine.request_principal import policy_principal_scope

    async with policy_principal_scope(user_id, session_id=f"device:{device_id}" if device_id else "device:picker",
                                      metadata={"client": DEVICE_POLICY_CLIENT}):
        return tuple(await admitted_tool_aliases(db, workspace_id))


def fallback_state(run: WorkflowRun) -> dict[str, Any] | None:
    state = dict(run.context or {}).get(FALLBACK_KEY)
    return dict(state) if isinstance(state, dict) else None


def remember_fallback(run: WorkflowRun, *, until: datetime, reset_known: bool, engine: str, reason: str) -> None:
    """The run went to the company models because its seat is at its limit until ``until`` (naive UTC)."""
    run.context = {**dict(run.context or {}), FALLBACK_KEY: {
        "until": until.replace(tzinfo=UTC).isoformat(), "reset_known": reset_known, "engine": engine,
        "reason": reason, "since": utc_now().isoformat()}}


def note_fallback_model(run: WorkflowRun, seat_model: str, company_model: str) -> bool:
    """Remember the company model a seat model runs on; ``True`` the first time this pair is used."""
    state = fallback_state(run)
    if state is None:
        return False
    pairs = dict(state.get("models") or {})
    if pairs.get(seat_model) == company_model:
        return False
    run.context = {**dict(run.context or {}), FALLBACK_KEY: {**state, "models": {**pairs, seat_model: company_model},
                                                             "seat_model": seat_model,
                                                             "fallback_model": company_model}}
    return True


def _until(state: dict[str, Any]) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(state.get("until") or ""))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def reset_passed(run: WorkflowRun, *, now: datetime | None = None) -> bool:
    state = fallback_state(run)
    until = _until(state) if state else None
    if until is None:
        return False
    current = now or utc_now()
    current = current if current.tzinfo is not None else current.replace(tzinfo=UTC)
    return current >= until


def clear_fallback(run: WorkflowRun) -> dict[str, Any] | None:
    state = fallback_state(run)
    run.context = {key: value for key, value in dict(run.context or {}).items() if key != FALLBACK_KEY}
    return state


def fallback_view(run: WorkflowRun) -> dict[str, Any] | None:
    """The run view's "on company fallback until <reset>" (``None`` while the run is on its seat or never was)."""
    from ..runtime_target.target import stored_target

    state = fallback_state(run)
    if state is None or dict(stored_target(run) or {}).get("profile") != "governed":
        return None
    until = str(state.get("until") or "") or None
    known = bool(state.get("reset_known"))
    when = until if known else f"{until} (reset not named by the account; the seat is tried again then)"
    return {"on_company_fallback": True, "until": until, "reset_known": known, "engine": state.get("engine"),
            "seat_model": state.get("seat_model") or None, "fallback_model": state.get("fallback_model") or None,
            "message": f"On company fallback until {when}."}


__all__ = ["EVENT_FALLBACK_MODEL", "EVENT_SEAT_RETURNED", "FALLBACK_KEY", "REASON_NO_SAME_CLASS",
           "admitted_company_aliases", "alias_class", "clear_fallback", "fallback_state", "fallback_view",
           "model_class", "note_fallback_model", "remember_fallback", "reset_passed", "same_class_alias"]
