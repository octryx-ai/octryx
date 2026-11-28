"""Sync the Model catalog from its providers: refresh, flag vanished models, propose new ones."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.providers import provider_supports_model_sync
from ...models import LLMModel, LLMProvider
from ...time_utils import utc_now
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..model_gateway.cost_contract_pricing import apply_model_pricing_update, resolve_model_pricing_update
from ..provider.model_sync import normalize_model_catalog_payload
from .alias_mirror import alias_entries, create_alias
from .contract import ERROR_ALIAS_EXISTS, ERROR_NOT_GATEWAY, ModelCatalogError
from .usage import load_usage
from .views import is_gateway, load_row, provider_label

AUDIT_SYNCED = "admin.model_catalog.synced"
AUDIT_ADDED = "admin.model_catalog.models_added"
AUDIT_ALIAS_ADDED = "admin.model_catalog.alias_added"
STATE_SYNCED = "synced"
STATE_FAILED = "failed"

BuildKwargs = Callable[..., Any]


def flag_vanished_models(models: Iterable[LLMModel], seen_ids: set[str]) -> int:
    now, flagged = utc_now(), 0
    for model in models:
        if model.model_id in seen_ids:
            model.upstream_gone_at = None
        elif model.last_synced_at is not None and model.upstream_gone_at is None:
            model.upstream_gone_at = now
            flagged += 1
    return flagged


def _gateway_listing(provider: LLMProvider) -> list[dict[str, Any]]:
    listing = []
    for alias, entry in alias_entries(provider).items():
        entry = entry if isinstance(entry, dict) else {}
        capabilities = entry.get("capabilities") if isinstance(entry.get("capabilities"), dict) else {}
        context = entry.get("context_limit")
        name = entry.get("display_name")
        listing.append({
            "id": alias,
            "name": name if isinstance(name, str) and name.strip() else alias,
            "context_length": context if isinstance(context, int) and not isinstance(context, bool) else None,
            "supports_tools": capabilities.get("tools") is True,
            "supports_vision": capabilities.get("vision") is True,
        })
    return listing


async def _upstream(db: AsyncSession, provider: LLMProvider, build_kwargs: BuildKwargs) -> list[dict[str, Any]]:
    if is_gateway(provider):
        return _gateway_listing(provider)
    from ...agent.providers import get_provider as get_provider_client

    client = get_provider_client(**(await build_kwargs(db, provider)))
    try:
        listed, _ignored = normalize_model_catalog_payload(await client.list_models())
    finally:
        await client.close()
    return [item for item in listed if item.get("id") or item.get("model_id")]


def _model_key(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("model_id") or "").strip()


async def _provider_rows(db: AsyncSession, provider_id: str) -> list[LLMModel]:
    return list((await db.execute(select(LLMModel).where(LLMModel.provider_id == provider_id))).scalars().all())


async def _syncable_providers(db: AsyncSession) -> list[LLMProvider]:
    providers = (await db.execute(select(LLMProvider).where(LLMProvider.is_active.is_(True)))).scalars().all()
    return [p for p in providers if is_gateway(p) or provider_supports_model_sync(driver=p.driver)]


def _proposal(provider: LLMProvider, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": provider.id,
        "provider": provider_label(provider),
        "model_id": _model_key(item),
        "display_name": str(item.get("name") or _model_key(item)),
        "context_length": item.get("context_length"),
        "supports_tools": item.get("supports_tools") is True,
        "supports_vision": item.get("supports_vision") is True,
    }


def _refresh(provider: LLMProvider, model: LLMModel, item: dict[str, Any]) -> None:
    if item.get("context_length"):
        model.context_length = item["context_length"]
    if not is_gateway(provider):
        apply_model_pricing_update(model, resolve_model_pricing_update(item, driver=provider.driver))
    model.last_synced_at = utc_now()


def _summary_row(provider: LLMProvider, model: LLMModel, usage) -> dict[str, Any]:
    ref = (model.provider_id, model.model_id)
    return {
        "id": model.id,
        "display_name": model.display_name or model.model_id,
        "provider": provider_label(provider),
        "enabled": bool(model.is_active),
        "used_by_workspaces": usage.workspaces(ref, alias=model.model_id if is_gateway(provider) else None),
        "order_position": usage.order_position(ref),
    }


async def sync_catalog(db: AsyncSession, *, build_kwargs: BuildKwargs, actor_id: str) -> dict[str, Any]:
    states, proposals, flagged = [], [], 0
    for provider in await _syncable_providers(db):
        try:
            listed = await _upstream(db, provider, build_kwargs)
        except Exception as error:  # noqa: BLE001 - one provider failing must not hide the others' results
            states.append({"provider_id": provider.id, "provider": provider_label(provider), "state": STATE_FAILED,
                           "error_class": type(error).__name__})
            continue
        rows = {model.model_id: model for model in await _provider_rows(db, provider.id)}
        by_id = {_model_key(item): item for item in listed}
        for model_id, item in by_id.items():
            if model_id in rows:
                _refresh(provider, rows[model_id], item)
            else:
                proposals.append(_proposal(provider, item))
        flagged += flag_vanished_models(rows.values(), set(by_id))
        states.append({"provider_id": provider.id, "provider": provider_label(provider), "state": STATE_SYNCED,
                       "listed": len(by_id)})
    await db.flush()
    record_admin_config_audit(db, actor_user_id=actor_id, action=AUDIT_SYNCED, resource_type="model_catalog",
                              resource_id="catalog", project_id=None, before=None, after=None,
                              details={"providers": states, "proposed": len(proposals), "flagged_gone": flagged})
    return {"providers": states, "new": proposals, **await catalog_attention(db)}


async def catalog_attention(db: AsyncSession) -> dict[str, Any]:
    usage = await load_usage(db)
    rows = (
        await db.execute(select(LLMProvider, LLMModel).join(LLMModel, LLMModel.provider_id == LLMProvider.id))
    ).all()
    gone = [_summary_row(p, m, usage) for p, m in rows if m.upstream_gone_at is not None]
    unaliased = [
        _summary_row(p, m, usage) for p, m in rows if is_gateway(p) and m.model_id not in alias_entries(p)
    ]
    return {"gone": gone, "gateway_without_alias": unaliased}


async def add_selected(
    db: AsyncSession, *, selected: list[dict[str, str]], build_kwargs: BuildKwargs, actor_id: str
) -> list[str]:
    wanted: dict[str, set[str]] = {}
    for item in selected:
        wanted.setdefault(str(item.get("provider_id") or ""), set()).add(str(item.get("model_id") or ""))
    created: list[str] = []
    for provider_id, model_ids in wanted.items():
        provider = await db.get(LLMProvider, provider_id)
        if provider is None:
            continue
        existing = {model.model_id for model in await _provider_rows(db, provider.id)}
        for item in await _upstream(db, provider, build_kwargs):
            model_id = _model_key(item)
            if model_id not in model_ids or model_id in existing:
                continue
            model = LLMModel(
                id=str(uuid.uuid4()), provider_id=provider.id, model_id=model_id,
                display_name=str(item.get("name") or model_id), context_length=item.get("context_length"),
                supports_streaming=True, supports_tools=item.get("supports_tools") is True,
                supports_vision=item.get("supports_vision") is True, is_active=False, last_synced_at=utc_now(),
                capabilities_json={"tools": item.get("supports_tools") is True,
                                   "vision": item.get("supports_vision") is True,
                                   "coding": False, "long_context": False},
                approved_data_categories=[],
            )
            if not is_gateway(provider):
                apply_model_pricing_update(model, resolve_model_pricing_update(item, driver=provider.driver))
            db.add(model)
            created.append(model.id)
    await db.flush()
    record_admin_config_audit(db, actor_user_id=actor_id, action=AUDIT_ADDED, resource_type="model_catalog",
                              resource_id="catalog", project_id=None, before=None, after={"created": created},
                              details={"requested": len(selected)})
    return created


async def add_alias_for(db: AsyncSession, *, model_id: str, actor_id: str) -> tuple[LLMProvider, LLMModel]:
    provider, model = await load_row(db, model_id)
    if not is_gateway(provider):
        raise ModelCatalogError(ERROR_NOT_GATEWAY)
    if model.model_id in alias_entries(provider):
        raise ModelCatalogError(ERROR_ALIAS_EXISTS, status=409)
    model.is_active = False
    create_alias(provider, model)
    record_admin_config_audit(db, actor_user_id=actor_id, action=AUDIT_ALIAS_ADDED, resource_type="model_catalog_model",
                              resource_id=model.id, project_id=None, before=None, after={"alias": model.model_id},
                              details={"provider_id": provider.id})
    await db.flush()
    return provider, model


__all__ = ["add_alias_for", "add_selected", "catalog_attention", "flag_vanished_models", "sync_catalog"]
