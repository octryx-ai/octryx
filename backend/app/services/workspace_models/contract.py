"""Workspace → Models: one list per Workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ControlPlaneRuntimeTarget, LLMModel, LLMProvider
from ..data_classification.levels import level_registry
from ..model_gateway.data_policy.classification import MODEL_DATA_POLICY_CLASSES
from ..model_gateway.litellm.alias_catalog import admitted_alias_entries
from ..model_gateway.litellm.runtime_admission import LITELLM_GATEWAY_DRIVER

MODE_ALL = "all_cleared"
MODE_SELECTED = "selected"
MODEL_POLICY_KEY = "model_policy"
RUNTIME_BINDING_PREFIX = "runtime-target:"
AUDIT_ACTION = "admin.workspace.models_updated"

ERROR_INVALID = "workspace_models_invalid"
ERROR_UNKNOWN = "workspace_model_unknown"
ERROR_NOT_CLEARED = "workspace_model_not_cleared"
ERROR_DEFAULT = "workspace_model_default_not_allowed"
ERROR_SEAT = "workspace_seat_invalid"
ERROR_EMPTY = "workspace_models_empty"
ERROR_SEAT_VIA_SEAT_ROUTE = "seat_setting_via_seat_route"
SEAT_ROUTE_HINT = "change it with PUT /api/v1/workspaces/{project_id}/agent-gateway/seat-mode"


class WorkspaceModelsError(ValueError):
    def __init__(self, code: str, path: str, reason: str = "") -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path
        self.reason = reason


@dataclass(slots=True)
class CatalogEntry:
    key: str
    label: str
    provider: str
    gateway: bool
    target_id: str | None = None
    alias: str | None = None
    cleared_up_to: str | None = None
    approved_for: list[str] = field(default_factory=list)
    temperature: float | None = None


def _catalog_keys(rows: list[tuple[str, str]]) -> list[str]:
    taken: set[str] = set()
    keys = []
    for provider, model in rows:
        prefixed = f"{provider or 'provider'}/{model}"
        for candidate in (model, prefixed, *(f"{prefixed}-{number}" for number in range(2, 52))):
            if candidate not in taken:
                taken.add(candidate)
                keys.append(candidate)
                break
    return keys


async def model_catalog(db: AsyncSession) -> list[CatalogEntry]:
    providers = {row.id: row for row in (await db.execute(select(LLMProvider))).scalars()}
    llm_rows = list((await db.execute(select(LLMModel))).scalars())
    names = {(row.provider_id, row.model_id): row.display_name for row in llm_rows if row.display_name}
    # The Runtime model catalog's stored key (``llm_models.catalog_key``) wins over the computed one.
    stored_keys = {(row.provider_id, row.model_id): row.catalog_key for row in llm_rows if row.catalog_key}
    # The temperature is set per model on its catalog row.
    temperatures = {(row.provider_id, row.model_id): row.temperature for row in llm_rows}
    origins: list[tuple[str, str]] = []
    targets = list(
        (
            await db.execute(
                select(ControlPlaneRuntimeTarget)
                .where(ControlPlaneRuntimeTarget.is_active.is_(True))
                .order_by(ControlPlaneRuntimeTarget.priority, ControlPlaneRuntimeTarget.created_at)
            )
        ).scalars()
    )
    aliases: dict[str, Any] = {}
    for provider in providers.values():
        if provider.is_active and provider.driver == LITELLM_GATEWAY_DRIVER:
            for entry in admitted_alias_entries(provider.config_json):
                aliases.setdefault(entry.alias, (provider, entry))
    pending: list[CatalogEntry] = []
    seen_aliases: set[str] = set()
    for target in targets:
        provider = providers.get(target.provider_id)
        gateway = provider is not None and provider.driver == LITELLM_GATEWAY_DRIVER
        alias_entry = aliases.get(target.model_id)[1] if gateway and target.model_id in aliases else None
        if alias_entry is not None:
            seen_aliases.add(target.model_id)
        origins.append((target.provider_id, target.model_id))
        pending.append(
            CatalogEntry(
                key="",
                provider=(provider.display_name or provider.name) if provider else "",
                label=(alias_entry.display_name if alias_entry and alias_entry.display_name else None)
                or names.get((target.provider_id, target.model_id))
                or target.model_id,
                gateway=gateway,
                target_id=target.id,
                alias=target.model_id if gateway else None,
                cleared_up_to=alias_entry.data_policy_class if alias_entry else None,
                approved_for=sorted(alias_entry.approved_data_categories) if alias_entry else [],
                temperature=temperatures.get((target.provider_id, target.model_id)),
            )
        )
    for alias, (provider, entry) in aliases.items():
        if alias in seen_aliases:
            continue
        origins.append((provider.id, alias))
        pending.append(
            CatalogEntry(
                key="",
                label=entry.display_name or alias,
                provider=provider.display_name or provider.name,
                gateway=True,
                alias=alias,
                cleared_up_to=entry.data_policy_class,
                approved_for=sorted(entry.approved_data_categories),
                temperature=temperatures.get((provider.id, alias)),
            )
        )
    model_ids = [entry.alias or next((t.model_id for t in targets if t.id == entry.target_id), "") for entry in pending]
    for entry, key in zip(
        pending,
        _catalog_keys([(entry.provider, model) for entry, model in zip(pending, model_ids, strict=True)]),
        strict=True,
    ):
        entry.key = key
    taken = {entry.key for entry in pending}
    for entry, origin in zip(pending, origins, strict=True):
        stored = stored_keys.get(origin)
        if stored and (stored == entry.key or stored not in taken):
            taken.discard(entry.key)
            entry.key = stored
            taken.add(stored)
    return pending


def cleared_for(entry: CatalogEntry, level: str | None) -> tuple[bool, str]:
    if not level:
        return False, "the Workspace has no level"
    registry = level_registry()
    this = registry.get(level)
    if this is None or not this.models_allowed:
        return False, f"no model may process {this.label if this else level}"
    if not entry.gateway or not entry.cleared_up_to:
        return True, ""  # direct models carry no clearance on this branch (Runtime → Model catalog adds it)
    if entry.cleared_up_to not in MODEL_DATA_POLICY_CLASSES:
        return False, "its clearance is unknown"
    if (registry.rank(entry.cleared_up_to) or 0) < (registry.rank(level) or 0):
        cleared = registry.get(entry.cleared_up_to)
        return False, f"cleared only up to {cleared.label if cleared else entry.cleared_up_to}"
    return True, ""


__all__ = [
    "AUDIT_ACTION",
    "ERROR_DEFAULT",
    "ERROR_EMPTY",
    "ERROR_INVALID",
    "ERROR_NOT_CLEARED",
    "ERROR_SEAT",
    "ERROR_UNKNOWN",
    "MODEL_POLICY_KEY",
    "RUNTIME_BINDING_PREFIX",
    "MODE_ALL",
    "MODE_SELECTED",
    "CatalogEntry",
    "WorkspaceModelsError",
    "cleared_for",
    "model_catalog",
]
