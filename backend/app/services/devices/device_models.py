"""The models a device job may run with (the model picker): the chat's Model pill and the send check.

The rows are the ones octryx-claude's ``/model`` offers for the same profile (``model_listing``), decided
for this user, this device and this Workspace:

- ``governed``: the Workspace's admitted company aliases (``admission.admitted_tool_aliases``);
- ``seat``: the Workspace seat policy's ``seat_models`` (subscription), plus ``company/<alias>`` rows only when
  the Workspace sets ``seat_allows_governed_models``; none when the Workspace refuses seat sessions.

An empty model means the device's own default (its ``main`` alias), exactly what a device job used before the
picker. A chosen model outside the list is refused before anything is written
(``denied: device_model_not_allowed``); every model call of the job is still decided by the gateway (seat and
governed admission, content routing), so this list never admits a call on its own.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_gateway.seat_policy import workspace_seat_decision
from ..model_gateway.inbound.admission import admitted_tool_aliases
from ..model_gateway.inbound.model_listing import PickerModel, company_models, seat_models
from ..model_gateway.litellm.alias_catalog import AliasEntry
from ..policy_engine.request_principal import SEAT_PROFILE, load_seat_principal, policy_principal_scope
from .contract import DEVICE_POLICY_CLIENT, PROFILE_GOVERNED, PROFILE_SEAT, STATE_DENIED

REASON_MODEL_NOT_ALLOWED = "device_model_not_allowed"


@dataclass(frozen=True, slots=True)
class DeviceModelOptions:
    profile: str
    models: tuple[PickerModel, ...]
    # Why the list is empty when the profile itself is refused (the seat decision's reason); "" otherwise.
    reason: str = ""

    def ids(self) -> frozenset[str]:
        return frozenset(model.id for model in self.models)

    def payload(self) -> dict:
        return {"profile": self.profile, "models": [model.row() for model in self.models],
                "reason": self.reason or None}


_MODEL_ID = re.compile(r"[a-z][a-z0-9.]*(?:-[a-z0-9.]+)*")


def readable_model_name(model_id: str) -> str:
    """A person's name for a model id the catalog does not name (else the pill shows the raw id):
    ``claude-opus-5-5`` -> ``Claude Opus 5.5``, ``claude-haiku-4-5-20251001`` -> ``Claude Haiku 4.5``. An id of
    another shape is returned as it is."""
    if not _MODEL_ID.fullmatch(model_id):
        return model_id
    words: list[str] = []
    version: list[str] = []
    for part in model_id.split("-"):
        if part.isdigit() and len(part) >= 8:
            continue  # a release date
        if part.isdigit():
            version.append(part)
            continue
        if version:
            words.append(".".join(version))
            version = []
        words.append(part[:1].upper() + part[1:])
    if version:
        words.append(".".join(version))
    return " ".join(words)


async def subscription_model_names(db: AsyncSession, model_ids: Sequence[str]) -> dict[str, str]:
    """The display name of each subscription model id: the model catalog's (``llm_models.display_name`` of the
    id itself or of a provider-prefixed ``<provider>.<id>`` row) when it names the model, else
    :func:`readable_model_name`. Never the bare id for a known Claude id."""
    from ...models import LLMModel  # noqa: PLC0415

    ids = [model_id for model_id in dict.fromkeys(model_ids) if model_id]
    if not ids:
        return {}
    rows = (await db.execute(select(LLMModel.model_id, LLMModel.display_name).where(or_(
        LLMModel.model_id.in_(ids), *[LLMModel.model_id.like(f"%.{model_id}") for model_id in ids],
    )).order_by(LLMModel.is_active.desc(), LLMModel.model_id))).all()
    names: dict[str, str] = {}
    for model_id in ids:
        for row_id, display_name in rows:
            name = str(display_name or "").strip()
            if (row_id == model_id or str(row_id).endswith(f".{model_id}")) and name and name not in (row_id, model_id):
                names[model_id] = name
                break
        names.setdefault(model_id, readable_model_name(model_id))
    return names


def _is_codex_model(model: str) -> bool:
    from ..workflow_runs.octryx.model_guard import codex_tier  # noqa: PLC0415

    return codex_tier(model) is not None


def _session_id(device_id: str) -> str:
    return f"device:{device_id}" if device_id else "device:picker"


async def device_model_options(db: AsyncSession, *, user_id: str, workspace_id: str, profile: str,
                               device_id: str = "") -> DeviceModelOptions:
    """The picker rows of ``profile`` for this user's device job in ``workspace_id``."""
    session_id = _session_id(device_id)
    if profile == PROFILE_GOVERNED:
        async with policy_principal_scope(user_id, session_id=session_id,
                                          metadata={"client": DEVICE_POLICY_CLIENT}):
            entries = await admitted_tool_aliases(db, workspace_id)
        return DeviceModelOptions(profile, tuple(company_models(entries)))
    if profile != PROFILE_SEAT:
        return DeviceModelOptions(profile, ())
    seat = await workspace_seat_decision(db, workspace_id, principal=await load_seat_principal(
        user_id, session_id=session_id, client=DEVICE_POLICY_CLIENT))
    if not seat.allowed:
        return DeviceModelOptions(profile, (), seat.reason)
    company: tuple[AliasEntry, ...] = ()
    if seat.governed_models:
        async with policy_principal_scope(user_id, session_id=session_id,
                                          metadata={"profile": SEAT_PROFILE, "client": DEVICE_POLICY_CLIENT}):
            company = await admitted_tool_aliases(db, workspace_id)
    names = await subscription_model_names(db, seat.models)
    return DeviceModelOptions(profile, tuple(seat_models(seat.models, company, names)))


async def check_device_model(db: AsyncSession, *, user_id: str, workspace_id: str, profile: str, device_id: str,
                             model: str) -> tuple[str, str] | None:
    """``None`` when ``model`` may be requested; else the refusal ``(state, reason)``."""
    if not model:
        return None
    if profile == PROFILE_SEAT and _is_codex_model(model):
        # A Codex model on the person's ChatGPT seat (a Codex run's target or its reviewer; the seat list
        # holds only Claude ids, so a Codex model would be refused there). Allowed when the Workspace allows the Codex
        # seat;
        # every call is still decided by the gateway (codex seat policy, engine, run guard); the Workspace's
        # ``codex_seat_models`` narrows it.
        decision = await workspace_seat_decision(db, workspace_id, principal=await load_seat_principal(
            user_id, session_id=_session_id(device_id), client=DEVICE_POLICY_CLIENT), codex=True)
        if not decision.allowed or (decision.models and model not in decision.models):
            return STATE_DENIED, REASON_MODEL_NOT_ALLOWED  # ``codex_seat_models`` narrows the Codex seat
        return None
    options = await device_model_options(db, user_id=user_id, workspace_id=workspace_id, profile=profile,
                                         device_id=device_id)
    if model not in options.ids():
        return STATE_DENIED, REASON_MODEL_NOT_ALLOWED
    return None


def nearest_model(model: str, options: list[str] | tuple[str, ...]) -> str:
    """The option sharing the longest name prefix with ``model`` (``claude-sonnet-5`` → ``claude-sonnet-5-5``), the
    first option on a tie; ``""`` without options."""
    def shared(option: str) -> int:
        count = 0
        for left, right in zip(model.lower().split("-"), option.lower().split("-"), strict=False):
            if left != right:
                break
            count += 1
        return count

    return max(options, key=shared) if options else ""


async def admitted_device_model(db: AsyncSession, *, user_id: str, workspace_id: str, profile: str, device_id: str,
                                model: str, check: Any = None) -> tuple[str, tuple[str, str] | None]:
    """``(model to use, refusal or None)``. A model outside the Workspace's list becomes the nearest listed one (allow
    by default; ``device_runs.tool_defaults.device_models: list_only`` refuses it). A seat the
    Workspace does not allow at all is still refused."""
    refused = await (check or check_device_model)(db, user_id=user_id, workspace_id=workspace_id, profile=profile,
                                                  device_id=device_id, model=model)
    if refused is None or refused[1] != REASON_MODEL_NOT_ALLOWED:
        return model, refused
    from ..agent_gateway.policy import load_workspace_policy  # noqa: PLC0415
    from .device_runs_keys import device_runs_section, tool_defaults  # noqa: PLC0415

    loaded = await load_workspace_policy(db, workspace_id) if workspace_id else None
    raw = loaded.policy.raw if loaded is not None and loaded.policy is not None else {}
    if tool_defaults(device_runs_section(raw))["device_models"] == "list_only":
        return model, refused
    if profile == PROFILE_SEAT and _is_codex_model(model):
        decision = await workspace_seat_decision(db, workspace_id, principal=await load_seat_principal(
            user_id, session_id=_session_id(device_id), client=DEVICE_POLICY_CLIENT), codex=True)
        options: list[str] = list(decision.models) if decision.allowed else []
    else:
        options = list((await device_model_options(db, user_id=user_id, workspace_id=workspace_id, profile=profile,
                                                   device_id=device_id)).ids())
    chosen = nearest_model(model, options)
    return (chosen, None) if chosen else (model, refused)


__all__ = [
    "REASON_MODEL_NOT_ALLOWED",
    "admitted_device_model",
    "nearest_model",
    "DeviceModelOptions",
    "check_device_model",
    "device_model_options",
    "readable_model_name",
    "subscription_model_names",
]
