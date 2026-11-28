"""Read and write the Workspace → Models contract by deriving the existing stores."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY

from ...models import AuditLog, Project
from ..agent_gateway.seat_policy_keys import (
    BASELINE_SEAT_MODELS,
    SEAT_ALLOWS_GOVERNED_MODELS_KEY,
    SEAT_MODE_ALLOWED,
    SEAT_MODE_FORBIDDEN,
    SEAT_MODE_KEY,
    SEAT_MODELS_KEY,
)
from ..data_classification.workspace_overrides import workspace_level_rules
from ..model_gateway.data_policy.classification import (
    DATA_POLICY_CONFIG_KEY,
    declared_classification,
)
from ..model_gateway.litellm.admission_types import StoredModelPolicy
from ..model_gateway.litellm.policy import effective_model_policy, model_alias_access_decision
from ..model_selection.task_models import (
    TASK_KEYS,
    TASKS,
    WORKSPACE_OVERRIDES_KEY,
    load_task_models,
    workspace_task_overrides,
)
from ..workspace_composition.admin_api import load_workspace_composition
from ..workspace_settings import bounds
from .contract import (
    AUDIT_ACTION,
    ERROR_DEFAULT,
    ERROR_EMPTY,
    ERROR_INVALID,
    ERROR_NOT_CLEARED,
    ERROR_SEAT,
    ERROR_SEAT_VIA_SEAT_ROUTE,
    ERROR_UNKNOWN,
    MODE_ALL,
    MODE_SELECTED,
    MODEL_POLICY_KEY,
    RUNTIME_BINDING_PREFIX,
    SEAT_ROUTE_HINT,
    CatalogEntry,
    WorkspaceModelsError,
    cleared_for,
    model_catalog,
)

SELECTED_ONLY = "selected_only"
ALL_INSTALLED = "all_installed"


def _config(project: Project) -> dict[str, Any]:
    return dict(project.config) if isinstance(project.config, Mapping) else {}


def _seat(config: Mapping[str, Any]) -> dict[str, Any]:
    policy = config.get(AGENT_GATEWAY_POLICY_CONFIG_KEY)
    policy = policy if isinstance(policy, Mapping) else {}
    return {
        "mode": SEAT_MODE_ALLOWED if policy.get(SEAT_MODE_KEY) == SEAT_MODE_ALLOWED else SEAT_MODE_FORBIDDEN,
        "subscription_models": list(policy.get(SEAT_MODELS_KEY) or BASELINE_SEAT_MODELS),
        "company_models_in_seat": policy.get(SEAT_ALLOWS_GOVERNED_MODELS_KEY) is True,
    }


def _runtime_bindings(workspace: Project) -> dict[str, Any]:
    return {
        binding.source_entity_id: binding
        for binding in workspace.workspace_capability_bindings
        if binding.capability_kind == "runtime" and binding.binding_key.startswith(RUNTIME_BINDING_PREFIX)
    }


def _granted(
    catalog: list[CatalogEntry], config: Mapping[str, Any], runtime_policy: Mapping[str, Any], bindings: dict[str, Any]
) -> set[str]:
    selected_only = runtime_policy.get("runtime_assignment_mode") == SELECTED_ONLY
    project_config = {MODEL_POLICY_KEY: effective_model_policy(config)}
    granted: set[str] = set()
    for entry in catalog:
        if entry.target_id and selected_only:
            binding = bindings.get(entry.target_id)
            if binding is None or not binding.is_enabled:
                continue
        if entry.gateway and not model_alias_access_decision(entry.alias, project_config).allowed:
            continue
        granted.add(entry.key)
    return granted


async def read_models(db: AsyncSession, project_id: str) -> dict[str, Any]:
    workspace = await load_workspace_composition(db, workspace_id=project_id)
    config = _config(workspace)
    catalog = await model_catalog(db)
    level = declared_classification(config.get(DATA_POLICY_CONFIG_KEY)) or None
    runtime_policy = dict(workspace.workspace_policy.runtime_policy or {}) if workspace.workspace_policy else {}
    default_bindings = dict(workspace.workspace_policy.default_bindings or {}) if workspace.workspace_policy else {}
    granted = _granted(catalog, config, runtime_policy, _runtime_bindings(workspace))
    cleared = {entry.key for entry in catalog if cleared_for(entry, level)[0]}
    restricted = runtime_policy.get("runtime_assignment_mode") == SELECTED_ONLY or bool(cleared - granted)
    mode = MODE_SELECTED if restricted else MODE_ALL
    selected = [entry.key for entry in catalog if entry.key in granted and entry.key in cleared] if restricted else []
    default_key = default_bindings.get("runtime", "")
    default = next(
        (
            entry.key
            for entry in catalog
            if entry.target_id and f"{RUNTIME_BINDING_PREFIX}{entry.target_id}" == default_key
        ),
        None,
    )
    rows = []
    for entry in catalog:
        is_cleared, reason = cleared_for(entry, level)
        rows.append(
            {
                "key": entry.key,
                "label": entry.label,
                "provider": entry.provider,
                "gateway": entry.gateway,
                "cleared_up_to": entry.cleared_up_to,
                "approved_for": entry.approved_for,
                "temperature": entry.temperature,
                "cleared": is_cleared,
                "reason": reason,
                "used_in": (["chat"] if entry.target_id else [])
                + (["coding_tools", "device_runs"] if entry.gateway else []),
                "allowed": is_cleared and (mode == MODE_ALL or entry.key in selected),
            }
        )
    seat = _seat(config)
    platform_tasks = await load_task_models(db)
    rules = await workspace_level_rules(db, config, level) if level else None
    gateway_allowed = any(row["allowed"] and row["gateway"] for row in rows)
    return {
        "contract": {
            "mode": mode,
            "selected": selected,
            "default": default,
            "task_overrides": workspace_task_overrides(config),
            "seat": seat,
        },
        "models": rows,
        # The background tasks and the platform's model for each (Runtime → Default & fallback → Task models).
        "tasks": [
            {"key": key, "label": label, "platform_model": platform_tasks.get(key)} for key, label in TASKS
        ],
        "level": level,
        "seat_checks": {
            "seat_allowed_at_level": bool(rules and rules.seat_in_policy),
            "company_model_allowed": gateway_allowed,
        },
    }


def _checked(body: Any, catalog: list[CatalogEntry], level: str | None) -> dict[str, Any]:
    if not isinstance(body, Mapping):
        raise WorkspaceModelsError(ERROR_INVALID, "")
    mode = body.get("mode")
    if mode not in (MODE_ALL, MODE_SELECTED):
        raise WorkspaceModelsError(ERROR_INVALID, "mode")
    by_key = {entry.key: entry for entry in catalog}
    selected = body.get("selected") or []
    if not isinstance(selected, list) or any(key not in by_key for key in selected):
        raise WorkspaceModelsError(ERROR_UNKNOWN, "selected")
    for key in selected:
        cleared, reason = cleared_for(by_key[key], level)
        if not cleared:
            raise WorkspaceModelsError(ERROR_NOT_CLEARED, f"selected.{key}", reason)
    if mode == MODE_SELECTED and not any(by_key[key].target_id for key in selected):
        raise WorkspaceModelsError(ERROR_EMPTY, "selected", "pick at least one model that serves chat and agents")
    default = body.get("default")
    if default is not None:
        entry = by_key.get(default)
        allowed = (
            entry is not None
            and entry.target_id
            and (default in selected if mode == MODE_SELECTED else cleared_for(entry, level)[0])
        )
        if not allowed:
            raise WorkspaceModelsError(ERROR_DEFAULT, "default", "the default must be an allowed chat model")
    task_overrides = body.get("task_overrides") or {}
    if not isinstance(task_overrides, Mapping) or set(task_overrides) - TASK_KEYS:
        raise WorkspaceModelsError(ERROR_INVALID, "task_overrides", "unknown task")
    for task, key in task_overrides.items():
        allowed = key in by_key and cleared_for(by_key[key], level)[0] and (mode == MODE_ALL or key in selected)
        if not allowed:
            raise WorkspaceModelsError(ERROR_INVALID, f"task_overrides.{task}", "a task model must be allowed here")
    seat = body.get("seat")
    # The seat is read-only here (single editor: the seat route writes every seat key): ``mode``,
    # ``subscription_models`` and ``company_models_in_seat`` are optional, and when sent they must have their shape
    # (``_seat_settings_unchanged`` compares them with the stored values).
    if seat is None:
        seat = {}
    if (
        not isinstance(seat, Mapping)
        or ("mode" in seat and seat.get("mode") not in (SEAT_MODE_ALLOWED, SEAT_MODE_FORBIDDEN))
        or ("company_models_in_seat" in seat and type(seat.get("company_models_in_seat")) is not bool)
        or ("subscription_models" in seat and not isinstance(seat.get("subscription_models"), list))
    ):
        raise WorkspaceModelsError(ERROR_SEAT, "seat")
    return {
        "mode": mode,
        "selected": list(dict.fromkeys(selected)),
        "default": default,
        "task_overrides": {str(task): str(key) for task, key in task_overrides.items()},
        "seat": dict(seat),
    }


def _seat_settings_unchanged(seat: Mapping[str, Any], stored: Mapping[str, Any], project_id: str) -> None:
    for field in ("mode", "subscription_models", "company_models_in_seat"):
        if field not in seat:
            continue
        sent = list(dict.fromkeys(seat[field])) if field == "subscription_models" else seat[field]
        if sent != stored[field]:
            raise WorkspaceModelsError(ERROR_SEAT_VIA_SEAT_ROUTE, f"seat.{field}",
                                       SEAT_ROUTE_HINT.format(project_id=project_id))


async def save_models(
    db: AsyncSession, project_id: str, body: Any, *, actor_id: str, platform_admin: bool
) -> dict[str, Any]:
    from ..admin.project.admin_project_config_service import apply_project_config_patch

    workspace = await load_workspace_composition(db, workspace_id=project_id)
    config = _config(workspace)
    level = declared_classification(config.get(DATA_POLICY_CONFIG_KEY)) or None
    catalog = await model_catalog(db)
    contract = _checked(body, catalog, level)
    before_view = await read_models(db, project_id)
    before = before_view["contract"]
    _seat_settings_unchanged(contract["seat"], _seat(config), project_id)
    if not platform_admin:  # a Workspace admin or owner may only narrow
        bounds.check_models(before, {row["key"] for row in before_view["models"] if row["allowed"]}, contract)
    by_key = {entry.key: entry for entry in catalog}
    selected = [by_key[key] for key in contract["selected"]]
    selected_targets = {entry.target_id for entry in selected if entry.target_id}
    default_target = by_key[contract["default"]].target_id if contract["default"] else None

    policy = workspace.workspace_policy
    runtime_policy = dict(policy.runtime_policy or {})
    runtime_policy["runtime_assignment_mode"] = SELECTED_ONLY if contract["mode"] == MODE_SELECTED else ALL_INSTALLED
    runtime_policy.pop("fallback_runtime_binding_key", None)  # read by nothing; failover is the platform's
    default_bindings = dict(policy.default_bindings or {})
    for target_id, binding in _runtime_bindings(workspace).items():
        binding.is_enabled = target_id in selected_targets or target_id == default_target
        binding.is_default = target_id == default_target
    if default_target:
        default_bindings["runtime"] = f"{RUNTIME_BINDING_PREFIX}{default_target}"
    else:
        default_bindings.pop("runtime", None)
    policy.runtime_policy, policy.default_bindings = runtime_policy, default_bindings

    # ``model_policy`` is written from the same contract as the runtime bindings, so the page reads back what it saved
    # (``read_models`` shows the effective grant of both): a denial of an alias the contract now allows would win over
    # the grant and is dropped; denials of other aliases stay.
    stored_policy = config.get(MODEL_POLICY_KEY) if isinstance(config.get(MODEL_POLICY_KEY), Mapping) else {}
    if contract["mode"] == MODE_ALL:
        granted_aliases = [
            entry.alias for entry in catalog if entry.gateway and entry.alias and cleared_for(entry, level)[0]
        ]
        model_policy: StoredModelPolicy = {"allowed_aliases": [], "allow_all_admitted_aliases": True}
    else:
        granted_aliases = [entry.alias for entry in selected if entry.gateway and entry.alias]
        model_policy = {"allowed_aliases": granted_aliases, "allow_all_admitted_aliases": False}
    model_policy["denied_aliases"] = [
        alias for alias in stored_policy.get("denied_aliases") or [] if str(alias).strip() not in granted_aliases
    ]
    # No seat key is written here: the seat route is their only editor (one audited key per call).
    await apply_project_config_patch(
        db,
        project=workspace,
        actor_user_id=actor_id,
        patch={
            MODEL_POLICY_KEY: model_policy,
            WORKSPACE_OVERRIDES_KEY: contract["task_overrides"],
        },
        replace_keys=frozenset({WORKSPACE_OVERRIDES_KEY}),
    )
    db.add(
        AuditLog(
            user_id=actor_id,
            action=AUDIT_ACTION,
            resource_type="workspace",
            resource_id=project_id,
            details={"before": before, "after": {**contract, "task_overrides": {}}},
        )
    )
    await db.flush()
    return await read_models(db, project_id)


__all__ = ["read_models", "save_models"]
