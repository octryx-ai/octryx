"""Catalog writes and audit records of a provider model sync."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import LLMModel, LLMProvider
from ....time_utils import utc_now
from ...model_catalog.sync import flag_vanished_models
from ...model_gateway.cost_contract_pricing import (
    apply_model_pricing_update,
    resolve_model_pricing_update,
)
from ...provider.model_sync import (
    apply_model_sync_provider_metadata,
    model_sync_failure_payload,
    model_sync_no_models_payload,
    model_sync_success_payload,
    normalize_model_catalog_payload,
    raise_model_sync_http_error,
)
from ..governance.admin_config_audit_service import record_admin_config_audit
from ._admin_provider_snapshots import _model_inventory_audit_snapshot
from .declared_capabilities import apply_declared, with_declared_capabilities


@dataclass
class ModelSyncTally:
    models_added: int = 0
    models_seen: int = 0
    models_ignored: int = 0
    capability_warnings: list[dict[str, Any]] = field(default_factory=list)


async def _provider_models(db: AsyncSession, provider: LLMProvider) -> list[LLMModel]:
    return (
        await db.execute(select(LLMModel).where(LLMModel.provider_id == provider.id).order_by(LLMModel.model_id))
    ).scalars().all()


def _update_existing_model(
    existing: LLMModel, model_payload: dict[str, Any], model_id_str: str, pricing_update: Any
) -> None:
    # The display name is the admin's (Model catalog); an upstream name only fills a blank one.
    existing.display_name = existing.display_name or model_payload.get("name") or model_id_str
    existing.context_length = model_payload.get("context_length") or existing.context_length
    # None means the gateway does not advertise the capability —
    # never downgrade an existing (possibly operator-set) value.
    if model_payload.get("supports_tools") is not None:
        existing.supports_tools = model_payload["supports_tools"]
    if model_payload.get("supports_vision") is not None:
        existing.supports_vision = model_payload["supports_vision"]
    apply_declared(existing, model_payload.get("declared_capabilities") or {})
    apply_model_pricing_update(existing, pricing_update)
    existing.last_synced_at = utc_now()


def _new_synced_model(
    provider: LLMProvider, model_payload: dict[str, Any], model_id_str: str, pricing_update: Any
) -> LLMModel:
    created = LLMModel(
        id=str(uuid.uuid4()),
        provider_id=provider.id,
        model_id=model_id_str,
        display_name=model_payload.get("name", model_id_str),
        context_length=model_payload.get("context_length"),
        supports_streaming=True,
        supports_tools=model_payload.get("supports_tools"),
        supports_vision=model_payload.get("supports_vision"),
        is_active=False,
        last_synced_at=utc_now(),
    )
    apply_model_pricing_update(created, pricing_update)
    return created


async def apply_synced_catalog(
    db: AsyncSession,
    provider: LLMProvider,
    raw_models: Any,
    *,
    before_models: list[LLMModel],
    tally: ModelSyncTally,
) -> None:
    api_models, tally.models_ignored = normalize_model_catalog_payload(raw_models)
    tally.models_seen = len(api_models)
    # Resolved before anything is written: a governed ``cost_contract``
    # is authoritative and can clear a price, so a malformed one must
    # fail the whole sync rather than half-apply it. A plain
    # ``pricing`` block stays non-authoritative and only ever adds a
    # price, which is what leaves non-gateway providers unchanged.
    # The server-owned driver key decides whether a ``cost_contract`` is
    # read at all: only the governed gateway driver builds its catalog
    # from an admitted alias contract, while every other driver returns
    # its upstream ``/models`` payload, which must never be able to clear
    # a price or stamp a governed source.
    pricing_updates = [
        resolve_model_pricing_update(payload, driver=provider.driver) for payload in api_models
    ]
    for model_payload, pricing_update in zip(api_models, pricing_updates, strict=True):
        model_id_str = model_payload.get("id") or model_payload.get("model_id") or ""
        if not model_id_str:
            continue
        # A gateway alias's declared tools/vision are the admin's: the probe never lowers or raises them, it
        # only reports a difference (llama-server's /models says "completion" only, which would otherwise turn
        # the catalog row and then the alias into tools=false).
        model_payload, warnings = with_declared_capabilities(provider, model_id_str, model_payload)
        tally.capability_warnings.extend(warnings)
        existing = (
            await db.execute(
                select(LLMModel).where(
                    LLMModel.provider_id == provider.id,
                    LLMModel.model_id == model_id_str,
                )
            )
        ).scalar_one_or_none()
        if existing:
            _update_existing_model(existing, model_payload, model_id_str, pricing_update)
        else:
            db.add(_new_synced_model(provider, model_payload, model_id_str, pricing_update))
            tally.models_added += 1
    flag_vanished_models(before_models, {str(item.get("id") or item.get("model_id") or "") for item in api_models})
    await db.flush()


async def record_sync_failure(
    db: AsyncSession,
    provider: LLMProvider,
    exc: Exception,
    *,
    before_models: list[LLMModel],
    supports_model_sync: bool,
    actor_user_id: str | None,
) -> None:
    all_models = await _provider_models(db, provider)
    active = sum(1 for model in all_models if model.is_active)
    result = model_sync_failure_payload(exc, total_models=len(all_models), active_models=active)
    apply_model_sync_provider_metadata(provider, result, checked_at=utc_now())
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.models_synced",
        resource_type="provider_models",
        resource_id=provider.id,
        project_id=None,
        before=_model_inventory_audit_snapshot(list(before_models)),
        after=_model_inventory_audit_snapshot(list(all_models)),
        details={
            "operation": "sync_provider_models",
            "models_added": 0,
            "models_seen": 0,
            "models_ignored": 0,
            "sync_state": result.get("sync_state"),
            "failure_state": result.get("failure_state"),
            "cache_state": result.get("cache_state"),
            "error_class": result.get("error_class"),
            "provider_supports_model_sync": supports_model_sync,
            "pricing_synced": False,
        },
    )
    await db.commit()
    raise_model_sync_http_error(result)


def _sync_result(
    tally: ModelSyncTally, *, all_models: list[LLMModel], supports_model_sync: bool
) -> dict[str, Any]:
    active = sum(1 for model in all_models if model.is_active)
    if tally.models_seen == 0:
        return model_sync_no_models_payload(
            total_models=len(all_models),
            active_models=active,
            provider_supports_model_sync=supports_model_sync,
        )
    return model_sync_success_payload(
        models_added=tally.models_added,
        models_seen=tally.models_seen,
        models_ignored=tally.models_ignored,
        total_models=len(all_models),
        active_models=active,
    )


async def finish_model_sync(
    db: AsyncSession,
    provider: LLMProvider,
    *,
    before_models: list[LLMModel],
    tally: ModelSyncTally,
    supports_model_sync: bool,
    actor_user_id: str | None,
) -> dict[str, Any]:
    all_models = await _provider_models(db, provider)
    result = _sync_result(tally, all_models=all_models, supports_model_sync=supports_model_sync)
    capability_warnings = tally.capability_warnings
    if capability_warnings:
        result["capability_warnings"] = capability_warnings  # the probe disagrees with the declaration: shown, kept
    apply_model_sync_provider_metadata(provider, result, checked_at=utc_now())
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.provider.models_synced",
        resource_type="provider_models",
        resource_id=provider.id,
        project_id=None,
        before=_model_inventory_audit_snapshot(list(before_models)),
        after=_model_inventory_audit_snapshot(list(all_models)),
        details={
            "operation": "sync_provider_models",
            "models_added": tally.models_added,
            "models_seen": tally.models_seen,
            "models_ignored": tally.models_ignored,
            "sync_state": result.get("sync_state"),
            "failure_state": result.get("failure_state"),
            "cache_state": result.get("cache_state"),
            "reason": result.get("reason"),
            "provider_supports_model_sync": supports_model_sync,
            **({"capability_warnings": capability_warnings} if capability_warnings else {}),
        },
    )
    await db.commit()
    return result
