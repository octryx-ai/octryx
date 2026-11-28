"""The runtime target of a workflow run: chosen at start, validated, stored on the run and on its chat thread."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkflowRun
from ....models.security.device import DEVICE_STATUS_ACTIVE, UserDevice
from ....time_utils import utc_now
from ...devices.chat_turn import EXECUTION_TARGET_METADATA_KEY, REFUSAL_MESSAGES
from ...devices.dispatch_gate import folder_allowlisted, normalized_folder
from ...devices.runner_pool import (
    POOL_DEVICE_ID,
    REASON_POOL_FORBIDDEN,
    is_pool_runner,
    pool_allowed,
    resolve_runner,
    runners_online,
)
from ..records import WorkflowRunError

CONTEXT_KEY = "runtime_target"
KIND_SERVER, KIND_DEVICE, KIND_TERMINAL = "server", "device", "terminal"
KINDS = (KIND_SERVER, KIND_DEVICE, KIND_TERMINAL)
KIND_AUTO = "auto"
EVENT_SET = "runtime_target_set"
_RECENT_RUNS = 20
_KIND_LABELS = {KIND_SERVER: "the Server", KIND_TERMINAL: "an octryx-claude terminal"}


def _invalid(message: str) -> WorkflowRunError:
    return WorkflowRunError("runtime_target_invalid", message, 422)


def parse_target(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        raw = {"kind": raw}
    if not isinstance(raw, dict):
        raise _invalid("The runtime target is an object with a kind.")
    kind = str(raw.get("kind") or "").strip()
    if kind == KIND_AUTO:
        return {"kind": KIND_AUTO}
    if kind not in KINDS:
        raise _invalid(f"The runtime target's kind is one of {', '.join((KIND_AUTO, *KINDS))}.")
    if kind != KIND_DEVICE:
        return {"kind": kind}
    device_id = str(raw.get("device_id") or "").strip()[:40]
    folder = normalized_folder(raw.get("folder"))
    profile, model = str(raw.get("profile") or "").strip()[:20], str(raw.get("model") or "").strip()[:200]
    if device_id == POOL_DEVICE_ID:
        return {"kind": kind, "device_id": device_id, "folder": "", "pool": True, "profile": profile, "model": model}
    if not device_id or not folder:
        raise _invalid("A device target names the device and one of its allowed folders.")
    return {"kind": kind, "device_id": device_id, "folder": folder,
            "profile": str(raw.get("profile") or "").strip()[:20], "model": str(raw.get("model") or "").strip()[:200]}


def _refused(state: str, reason: str) -> WorkflowRunError:
    return WorkflowRunError(reason, REFUSAL_MESSAGES.get(reason, f"{state}: {reason}"),
                            403 if state == "denied" else 409)


async def _on_pool(db: AsyncSession, *, user: User, project_id: str | None,
                   provenance: dict[str, Any]) -> dict[str, Any]:
    validated = await validate_target(db, user=user, project_id=project_id,
                                      raw={"kind": KIND_DEVICE, "device_id": POOL_DEVICE_ID})
    return {**dict(validated or {}), **provenance}


async def validate_target(db: AsyncSession, *, user: User, project_id: str | None, raw: Any,
                          repository: str | None = None) -> dict[str, Any] | None:
    from ...devices.device_models import admitted_device_model
    from ...devices.device_policy import device_run_decision

    target = parse_target(raw)
    if target is None or target["kind"] == KIND_SERVER:  # the server's agents are its runners
        return await _on_pool(db, user=user, project_id=project_id, provenance={"resolved_from": KIND_SERVER})
    if target is not None and target["kind"] == KIND_AUTO:
        from .auto import resolve_auto

        resolved = await resolve_auto(db, user=user, project_id=project_id, repository=repository)
        provenance = {"resolved_from": KIND_AUTO, "reason": resolved["reason"]}
        if resolved["kind"] == KIND_SERVER:
            return await _on_pool(db, user=user, project_id=project_id, provenance=provenance)
        if resolved["kind"] != KIND_DEVICE:
            return {"kind": resolved["kind"], **provenance}
        validated = await validate_target(db, user=user, project_id=project_id, raw=resolved)
        return {**dict(validated or {}), **provenance}
    if target is None or target["kind"] != KIND_DEVICE:
        return target
    if target.get("pool"):
        if target["profile"] == "seat":  # no runner holds a seat: the run pauses for a takeover (``seat_required``)
            return {**target, "device_name": "the server runners"}
        choice = await resolve_runner(db, workspace_id=project_id, owner_user_id=user.id)
        if isinstance(choice, str):
            raise _refused("denied" if choice == REASON_POOL_FORBIDDEN else "needs_configuration", choice)
        target = {**target, "device_id": choice.device.id, "folder": choice.folder}
        if not target["model"]:  # a runner has no model of its own: the Workspace's first governed one
            from ...devices.chat_turn import pool_default_model

            target["model"] = await pool_default_model(db, user_id=user.id, workspace_id=project_id or "",
                                                       device_id=choice.device.id)
    device = await db.get(UserDevice, target["device_id"])
    runner = await is_pool_runner(db, device) and await pool_allowed(db, project_id)
    if device is None or (device.owner_user_id != user.id and not runner):
        raise WorkflowRunError("runtime_device_not_owner", "Only one of your own devices runs your workflow run.", 403)
    if device.status != DEVICE_STATUS_ACTIVE:
        raise WorkflowRunError("runtime_device_revoked", "This device is revoked.", 403)
    if not folder_allowlisted(target["folder"], list(device.folders or [])):
        raise WorkflowRunError("runtime_folder_not_allowed", "This folder is not one of the device's allowed folders.",
                               422)
    profiles = [str(item) for item in device.profiles or []]
    profile = target["profile"] or ("governed" if "governed" in profiles else (profiles[0] if profiles else ""))
    if profile not in profiles:
        raise WorkflowRunError("runtime_profile_unavailable", "This profile is not available on the device.", 422)
    decision = await device_run_decision(db, user_id=user.id, device=device, workspace_id=project_id,
                                         profile=profile, folder_allowlisted=True)
    if not decision.allowed:
        raise _refused(decision.state, decision.reason)
    model, refused = await admitted_device_model(db, user_id=user.id, workspace_id=project_id or "", profile=profile,
                                                 device_id=device.id, model=target["model"])
    if refused:
        raise _refused(refused[0], refused[1])
    mapped = {"model": model, "model_requested": target["model"]} if model != target["model"] else {}
    return {**target, **mapped, "profile": profile, "device_name": device.name}


def stored_target(run: WorkflowRun | None) -> dict[str, Any] | None:
    target = dict(run.context or {}).get(CONTEXT_KEY) if run is not None else None
    return dict(target) if isinstance(target, dict) and target.get("kind") in KINDS else None


def with_target(context: dict[str, Any] | None, target: dict[str, Any] | None, *, actor_id: str | None
                ) -> dict[str, Any]:
    if target is None:
        return dict(context or {})
    return {**dict(context or {}), CONTEXT_KEY: {**target, "chosen_by": actor_id, "at": utc_now().isoformat()}}


def apply_to_thread(thread: Session | None, target: dict[str, Any] | None) -> None:
    if thread is None or target is None:
        return
    metadata = dict(thread.metadata_ or {})
    if target["kind"] == KIND_DEVICE:
        metadata[EXECUTION_TARGET_METADATA_KEY] = {key: target.get(key) or "" for key in
                                                   ("device_id", "folder", "profile", "model")} | {"kind": KIND_DEVICE}
    else:
        metadata.pop(EXECUTION_TARGET_METADATA_KEY, None)
    thread.metadata_ = metadata


def target_label(target: dict[str, Any] | None) -> str:
    if not target:
        return "the Server"
    if target["kind"] != KIND_DEVICE:
        return _KIND_LABELS[target["kind"]]
    if target.get("pool"):
        return "the server runners"
    return f"{target.get('device_name') or 'your device'} ({target.get('folder')}, {target.get('profile')})"


def target_view(run: WorkflowRun) -> dict[str, Any] | None:
    from ...devices.hub import device_hub

    target = stored_target(run)
    if target is None:
        return None
    view = {key: target.get(key) for key in ("kind", "device_id", "device_name", "folder", "profile", "model",
                                             "resolved_from", "reason")
            if target.get(key) is not None}
    if target["kind"] == KIND_DEVICE:
        view["online"] = device_hub.connected(str(target.get("device_id") or ""))
    return {**view, "label": target_label(target)}


def option_key(target: dict[str, Any]) -> str:
    if target["kind"] != KIND_DEVICE:
        return target["kind"]
    return f"device:{target['device_id']}:{target['profile']}:{target['folder']}"


async def _first_runtime(db: AsyncSession) -> Any:
    from sqlalchemy.orm import selectinload

    from ....models import ControlPlaneRuntimeTarget

    return (await db.execute(select(ControlPlaneRuntimeTarget).where(ControlPlaneRuntimeTarget.is_active.is_(True))
                             .options(selectinload(ControlPlaneRuntimeTarget.provider))
                             .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
                             .limit(1))).scalars().first()


async def governed_model_label(db: AsyncSession) -> str | None:
    target = await _first_runtime(db)
    if target is None or not target.model_id:
        return None
    provider = target.provider.display_name or target.provider.name if target.provider is not None else ""
    return f"{target.model_id} ({provider})" if provider else str(target.model_id)


# The public model APIs a first start points a provider at (``env_model_access``): they never answer without a key.
_KEYED_HOSTS = frozenset({"api.anthropic.com", "api.openai.com"})


async def governed_key_missing(db: AsyncSession) -> bool:
    from urllib.parse import urlsplit

    target = await _first_runtime(db)
    provider = getattr(target, "provider", None)
    if provider is None or provider.api_key_secret_ref or (provider.auth_mode or "api_key") != "api_key":
        return False
    return (urlsplit(str(provider.endpoint_url or "")).hostname or "") in _KEYED_HOSTS


GOVERNED_KEY_MISSING = ("Governed runs cannot run here yet: the platform's model has no API key (an admin adds it "
                        "under Admin › Models › Providers). Log in with your Claude subscription on your device "
                        "(`octryx-claude login --seat`) to run on your seat.")


async def auto_help(db: AsyncSession) -> str:
    if await governed_key_missing(db):
        return f"Uses a free seat on your device. {GOVERNED_KEY_MISSING}"
    model = await governed_model_label(db)
    governed = f"governed with {model}" if model else "governed with the platform's model"
    return (f"Uses a free seat on your device first. Otherwise it runs {governed}: on your device when one is usable, "
            "else on the Server.")


async def target_options(db: AsyncSession, *, user: User) -> list[dict[str, Any]]:
    from ...devices.hub import device_hub

    options = [{"key": KIND_AUTO, "label": "Automatic", "target": {"kind": KIND_AUTO},
                "help": await auto_help(db)},
               {"key": KIND_SERVER, "label": "Server", "target": {"kind": KIND_SERVER}},
               {"key": KIND_TERMINAL, "label": "octryx-claude terminal (prepares at its next launch)",
                "target": {"kind": KIND_TERMINAL}}]
    keyless = await governed_key_missing(db)
    if online_runners := await runners_online(db):
        # Server runners only run governed: no person's seat ever reaches them.
        pool = {"kind": KIND_DEVICE, "device_id": POOL_DEVICE_ID, "folder": "", "pool": True, "profile": "governed"}
        options.append({"key": option_key(pool), "target": pool, "online": True, "label": "Server runners · governed",
                        "help": f"A fresh folder on one of {online_runners} platform runner(s); nothing of your "
                                "machine is reachable from there."})
    devices = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == user.id, UserDevice.status == DEVICE_STATUS_ACTIVE).order_by(UserDevice.name)
    )).scalars().all()
    for device in devices:
        online = device_hub.reachable(device)
        for folder in device.folders or []:
            for profile in device.profiles or []:
                target = {"kind": KIND_DEVICE, "device_id": device.id, "folder": str(folder), "profile": str(profile)}
                state = "online" if online else "offline: the run waits until it connects"
                folder_name = str(folder).rstrip("/").rsplit("/", 1)[-1] or str(folder)
                note = f" · {GOVERNED_KEY_MISSING}" if keyless and str(profile) == "governed" else ""
                options.append({"key": option_key(target), "target": target, "online": online,
                                "label": f"{device.name} · {folder_name} · {profile}",
                                "help": f"{folder} · {state}{note}"})
    return options


async def last_target(db: AsyncSession, *, user: User, project_id: str | None) -> dict[str, Any] | None:
    rows = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.requested_by == user.id, WorkflowRun.project_id == project_id,
    ).order_by(WorkflowRun.created_at.desc()).limit(_RECENT_RUNS))).scalars().all()
    return next((target for target in map(stored_target, rows) if target is not None), None)


async def target_choices(db: AsyncSession, *, user: User, project_id: str | None) -> dict[str, Any]:
    options = await target_options(db, user=user)
    last = await last_target(db, user=user, project_id=project_id)
    keys = {option["key"] for option in options}
    explicit = last is not None and last.get("resolved_from") != "auto" and option_key(last) in keys
    return {"options": options, "default": option_key(last) if explicit else KIND_AUTO}


__all__ = ["CONTEXT_KEY", "EVENT_SET", "KIND_AUTO", "KIND_DEVICE", "KIND_SERVER", "KIND_TERMINAL", "apply_to_thread",
           "last_target", "option_key", "parse_target", "stored_target",
           "target_choices", "target_label", "target_options",
           "target_view", "validate_target", "with_target"]
