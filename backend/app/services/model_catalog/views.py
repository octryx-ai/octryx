"""Read the Model catalog: one row per ``llm_models`` row with its provider, usage, status and issues."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..model_gateway.litellm.alias_catalog import resolve_alias_admission
from .alias_mirror import alias_entries
from .clearance import CLEARANCE_LEVELS, GATEWAY_DRIVER
from .contract import (
    CAPABILITY_KEYS,
    ERROR_NOT_FOUND,
    ISSUE_ALIAS_INCOMPLETE,
    ISSUE_COST_DRIFT,
    ISSUE_GONE_UPSTREAM,
    ISSUE_NO_ALIAS,
    ISSUE_NOT_CLEARED,
    ISSUE_PROVIDER_OFF,
    STATUS_ENABLED,
    STATUS_NEEDS_ATTENTION,
    STATUS_OFF,
    ModelCatalogError,
    capabilities_of,
)
from .usage import CatalogUsage, load_usage


def provider_label(provider: LLMProvider) -> str:
    return str(provider.display_name or provider.name or "")


def is_gateway(provider: LLMProvider) -> bool:
    return provider.driver == GATEWAY_DRIVER


def _gateway_state(provider: LLMProvider, model: LLMModel) -> dict[str, Any] | None:
    if not is_gateway(provider):
        return None
    present = model.model_id in alias_entries(provider)
    admission = resolve_alias_admission(model.model_id, provider.config_json) if present else None
    return {
        "alias_present": present,
        "admitted": bool(admission and admission.admitted),
        "denial_reason": admission.denial_reason if admission is not None else "",
    }


def _issues(provider: LLMProvider, model: LLMModel, gateway: dict[str, Any] | None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if gateway is not None and not gateway["alias_present"]:
        issues.append({"code": ISSUE_NO_ALIAS, "detail": ""})
    elif gateway is not None and not gateway["admitted"]:
        issues.append({"code": ISSUE_ALIAS_INCOMPLETE, "detail": gateway["denial_reason"]})
    if model.upstream_gone_at is not None:
        issues.append({"code": ISSUE_GONE_UPSTREAM, "detail": ""})
    if not provider.is_active:
        issues.append({"code": ISSUE_PROVIDER_OFF, "detail": ""})
    if model.is_active and not model.cleared_up_to:
        issues.append({"code": ISSUE_NOT_CLEARED, "detail": ""})
    if gateway is not None and gateway["alias_present"] and (drift := _cost_drift(provider, model)):
        issues.append({"code": ISSUE_COST_DRIFT, "detail": drift})
    return issues


_COST_FIELDS = (
    ("pricing_input", "input_per_million_usd"), ("pricing_output", "output_per_million_usd"),
    ("pricing_cache_read", "cache_read_per_million_usd"), ("pricing_cache_write", "cache_write_per_million_usd"),
)


def _cost_drift(provider: LLMProvider, model: LLMModel) -> str:
    contract = dict(dict(alias_entries(provider).get(model.model_id) or {}).get("cost") or {})
    if contract.get("source") not in (None, "catalog_pricing"):
        return ""
    drifted = [row for row, key in _COST_FIELDS
               if getattr(model, row) is not None and contract.get(key) != getattr(model, row)]
    return ",".join(drifted)


def cost_editable(provider: LLMProvider, model: LLMModel) -> bool:
    return is_gateway(provider) or not model.cost_source


def serialize_row(provider: LLMProvider, model: LLMModel, usage: CatalogUsage) -> dict[str, Any]:
    gateway = _gateway_state(provider, model)
    issues = _issues(provider, model, gateway)
    ref = (model.provider_id, model.model_id)
    return {
        "id": model.id,
        "catalog_key": model.catalog_key,
        "model_id": model.model_id,
        "display_name": model.display_name or model.model_id,
        "provider": {
            "id": provider.id,
            "display_name": provider_label(provider),
            "is_gateway": is_gateway(provider),
            "is_active": bool(provider.is_active),
        },
        "enabled": bool(model.is_active),
        "capabilities": capabilities_of(model),
        "cleared_up_to": model.cleared_up_to,
        "approved_data_categories": sorted(set(model.approved_data_categories or [])),
        "temperature": model.temperature,
        "max_output_tokens": model.max_tokens_per_request,
        "context_length": model.context_length,
        "cost": {
            "pricing_input": model.pricing_input,
            "pricing_output": model.pricing_output,
            "pricing_cache_read": model.pricing_cache_read,
            "pricing_cache_write": model.pricing_cache_write,
            "cost_source": model.cost_source,
            "contract_reference": _contract_reference(provider, model),
            "editable": cost_editable(provider, model),
        },
        "used_by_workspaces": usage.workspaces(ref, alias=model.model_id if gateway else None),
        "order_position": usage.order_position(ref),
        "status": STATUS_NEEDS_ATTENTION if issues else (STATUS_ENABLED if model.is_active else STATUS_OFF),
        "issues": issues,
        "gateway": gateway,
        "last_synced_at": model.last_synced_at.isoformat() if model.last_synced_at else None,
        "upstream_gone_at": model.upstream_gone_at.isoformat() if model.upstream_gone_at else None,
    }


def _contract_reference(provider: LLMProvider, model: LLMModel) -> str:
    if not is_gateway(provider):
        return ""
    entry = alias_entries(provider).get(model.model_id)
    cost = entry.get("cost") if isinstance(entry, dict) else None
    return str(cost.get("contract_reference") or "") if isinstance(cost, dict) else ""


async def _rows(db: AsyncSession) -> list[tuple[LLMProvider, LLMModel]]:
    return list(
        (
            await db.execute(
                select(LLMProvider, LLMModel)
                .join(LLMModel, LLMModel.provider_id == LLMProvider.id)
                .order_by(LLMProvider.display_name, LLMModel.display_name, LLMModel.model_id)
            )
        ).all()
    )


async def list_catalog(db: AsyncSession) -> dict[str, Any]:
    usage = await load_usage(db)
    rows = await _rows(db)
    providers = (await db.execute(select(LLMProvider).order_by(LLMProvider.display_name))).scalars().all()
    return {
        "models": [serialize_row(provider, model, usage) for provider, model in rows],
        "providers": [
            {"id": provider.id, "display_name": provider_label(provider), "is_active": bool(provider.is_active)}
            for provider in providers
        ],
        "clearance_levels": list(CLEARANCE_LEVELS),
        "capability_keys": list(CAPABILITY_KEYS),
    }


async def load_row(db: AsyncSession, model_id: str) -> tuple[LLMProvider, LLMModel]:
    model = await db.get(LLMModel, model_id)
    provider = await db.get(LLMProvider, model.provider_id) if model is not None else None
    if model is None or provider is None:
        raise ModelCatalogError(ERROR_NOT_FOUND, status=404)
    return provider, model


async def catalog_row(db: AsyncSession, model_id: str) -> dict[str, Any]:
    provider, model = await load_row(db, model_id)
    return serialize_row(provider, model, await load_usage(db))


__all__ = ["catalog_row", "cost_editable", "is_gateway", "list_catalog", "load_row", "provider_label", "serialize_row"]
