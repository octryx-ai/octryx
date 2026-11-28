"""Save a catalog model: General (enabled, display name, capabilities), Data (clearance, approved for), Generation
(temperature, max output) and Cost (``cost.py``)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import LLMModel, LLMProvider
from ..admin.governance.admin_config_audit_service import record_admin_config_audit
from ..governance.approval_rule import load_approval_rule
from .alias_mirror import mirror_into_alias
from .clearance import is_raise, normalized_clearance
from .contract import (
    CAPABILITY_KEYS,
    ERROR_CAPABILITIES_INVALID,
    ERROR_CATEGORIES_INVALID,
    ERROR_CONTEXT_LENGTH_GOVERNED,
    ERROR_CONTEXT_LENGTH_INVALID,
    ERROR_DISPLAY_NAME_INVALID,
    ERROR_FIELD_UNKNOWN,
    ERROR_MAX_OUTPUT_INVALID,
    ERROR_TEMPERATURE_INVALID,
    MAX_CONTEXT_LENGTH,
    MAX_DISPLAY_NAME_CHARS,
    MAX_TEMPERATURE,
    MIN_CONTEXT_LENGTH,
    MIN_MAX_OUTPUT_TOKENS,
    ModelCatalogError,
    capabilities_of,
)
from .cost import apply_cost
from .views import is_gateway, load_row

AUDIT_ACTION = "admin.model_catalog.model_updated"
AUDIT_RESOURCE = "model_catalog_model"
FIELDS = frozenset(
    {"enabled", "display_name", "capabilities", "cleared_up_to", "approved_data_categories", "temperature",
     "max_output_tokens", "context_length", "cost"}
)
MAX_CATEGORIES = 30
_CATEGORY_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def snapshot(model: LLMModel) -> dict[str, Any]:
    return {
        "enabled": bool(model.is_active),
        "display_name": model.display_name,
        "capabilities": capabilities_of(model),
        "cleared_up_to": model.cleared_up_to,
        "approved_data_categories": sorted(set(model.approved_data_categories or [])),
        "temperature": model.temperature,
        "max_output_tokens": model.max_tokens_per_request,
        "context_length": model.context_length,
        "cost_source": model.cost_source,
        "pricing_input": model.pricing_input,
        "pricing_output": model.pricing_output,
        "pricing_cache_read": model.pricing_cache_read,
        "pricing_cache_write": model.pricing_cache_write,
    }


def _display_name(value: Any) -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name or len(name) > MAX_DISPLAY_NAME_CHARS or not name.isprintable():
        raise ModelCatalogError(ERROR_DISPLAY_NAME_INVALID)
    return name


def _capabilities(model: LLMModel, value: Any) -> dict[str, bool]:
    if not isinstance(value, dict) or set(value) - set(CAPABILITY_KEYS):
        raise ModelCatalogError(ERROR_CAPABILITIES_INVALID)
    if not all(isinstance(flag, bool) for flag in value.values()):
        raise ModelCatalogError(ERROR_CAPABILITIES_INVALID)
    return {**capabilities_of(model), **value}


def _categories(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_CATEGORIES:
        raise ModelCatalogError(ERROR_CATEGORIES_INVALID)
    if not all(isinstance(item, str) and _CATEGORY_ID.match(item) for item in value):
        raise ModelCatalogError(ERROR_CATEGORIES_INVALID)
    return sorted(set(value))


def _temperature(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ModelCatalogError(ERROR_TEMPERATURE_INVALID)
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        raise ModelCatalogError(ERROR_TEMPERATURE_INVALID) from None
    if not 0.0 <= temperature <= MAX_TEMPERATURE:
        raise ModelCatalogError(ERROR_TEMPERATURE_INVALID)
    return temperature


def _max_output(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < MIN_MAX_OUTPUT_TOKENS:
        raise ModelCatalogError(ERROR_MAX_OUTPUT_INVALID)
    return value


def _context_length(provider: LLMProvider, value: Any) -> int | None:
    # A gateway model's window comes from its gateway contract (and its sync); only a direct model's is kept here,
    # because a provider listing such as Bedrock's carries none and the runtime budgets need the real capacity.
    if is_gateway(provider):
        raise ModelCatalogError(ERROR_CONTEXT_LENGTH_GOVERNED)
    if value in (None, "", 0):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_CONTEXT_LENGTH <= value <= MAX_CONTEXT_LENGTH:
        raise ModelCatalogError(ERROR_CONTEXT_LENGTH_INVALID)
    return value


def _apply(provider: LLMProvider, model: LLMModel, payload: dict[str, Any]) -> None:
    values: dict[str, Any] = {}
    if "enabled" in payload:
        if not isinstance(payload["enabled"], bool):
            raise ModelCatalogError(ERROR_FIELD_UNKNOWN)
        values["is_active"] = payload["enabled"]
    if "display_name" in payload:
        values["display_name"] = _display_name(payload["display_name"])
    if "capabilities" in payload:
        values["capabilities_json"] = _capabilities(model, payload["capabilities"])
    if "cleared_up_to" in payload:
        try:
            values["cleared_up_to"] = normalized_clearance(payload["cleared_up_to"])
        except ValueError as error:
            raise ModelCatalogError(str(error)) from None
    if "approved_data_categories" in payload:
        values["approved_data_categories"] = _categories(payload["approved_data_categories"])
    if "temperature" in payload:
        values["temperature"] = _temperature(payload["temperature"])
    if "max_output_tokens" in payload:
        values["max_tokens_per_request"] = _max_output(payload["max_output_tokens"])
    if "context_length" in payload:
        values["context_length"] = _context_length(provider, payload["context_length"])
    if "cost" in payload:
        if not isinstance(payload["cost"], dict):
            raise ModelCatalogError(ERROR_FIELD_UNKNOWN)
        apply_cost(provider, model, payload["cost"], gateway=is_gateway(provider))
    for field, value in values.items():
        setattr(model, field, value)
    if "capabilities_json" in values:
        # The runtime still reads the supports flags (tool use, image input); they follow the explicit checkbox.
        model.supports_tools = values["capabilities_json"]["tools"]
        model.supports_vision = values["capabilities_json"]["vision"]


async def update_catalog_model(
    db: AsyncSession, *, model_id: str, payload: Any, actor_id: str
) -> tuple[LLMProvider, LLMModel]:
    if not isinstance(payload, dict) or not payload or set(payload) - FIELDS:
        raise ModelCatalogError(ERROR_FIELD_UNKNOWN)
    provider, model = await load_row(db, model_id)
    before = snapshot(model)
    _apply(provider, model, payload)
    mirrored = mirror_into_alias(provider, model) if is_gateway(provider) else False
    after = snapshot(model)
    details: dict[str, Any] = {
        "catalog_key": model.catalog_key,
        "provider_id": provider.id,
        "fields": sorted(payload),
        "alias_mirrored": mirrored,
    }
    if is_raise(before["cleared_up_to"], after["cleared_up_to"]):
        details["clearance_raise"] = {
            "before": before["cleared_up_to"],
            "after": after["cleared_up_to"],
            "approval_rule": await load_approval_rule(db),
            "approval": "applied_directly",
        }
    record_admin_config_audit(
        db, actor_user_id=actor_id, action=AUDIT_ACTION, resource_type=AUDIT_RESOURCE, resource_id=model.id,
                                                                                       project_id=None,
        before=before, after=after, details=details,
    )
    await db.flush()
    return provider, model


__all__ = ["AUDIT_ACTION", "update_catalog_model"]
