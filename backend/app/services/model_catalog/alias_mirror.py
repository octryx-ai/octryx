"""Mirror a catalog row into its gateway alias entry."""

from __future__ import annotations

import copy
from typing import Any

from ...models import LLMModel, LLMProvider
from ..model_gateway.litellm.alias_catalog import GATEWAY_CONFIG_KEY
from .contract import CAPABILITY_TOOLS, CAPABILITY_VISION, capabilities_of

ALIASES_KEY = "aliases"


def alias_entries(provider: LLMProvider) -> dict[str, Any]:
    config = provider.config_json if isinstance(provider.config_json, dict) else {}
    section = config.get(GATEWAY_CONFIG_KEY)
    aliases = section.get(ALIASES_KEY) if isinstance(section, dict) else None
    return aliases if isinstance(aliases, dict) else {}


def has_alias(provider: LLMProvider, alias: str) -> bool:
    return alias in alias_entries(provider)


def _write_entry(provider: LLMProvider, alias: str, entry: dict[str, Any]) -> None:
    # A new dict on every write: an in-place mutation of a JSON column is not detected by the ORM.
    config = copy.deepcopy(provider.config_json) if isinstance(provider.config_json, dict) else {}
    section = config.setdefault(GATEWAY_CONFIG_KEY, {})
    section.setdefault(ALIASES_KEY, {})[alias] = entry
    provider.config_json = config


def _governed_fields(entry: dict[str, Any], model: LLMModel) -> dict[str, Any]:
    # ``capabilities_of`` falls back to the ``supports_*`` columns for a row whose ``capabilities_json`` was never
    # written: reading the raw column would mirror ``tools=false`` and the gateway would refuse a tool-capable model.
    capabilities = capabilities_of(model)
    alias_capabilities = dict(entry.get("capabilities") or {}) if isinstance(entry.get("capabilities"), dict) else {}
    alias_capabilities["tools"] = capabilities[CAPABILITY_TOOLS]
    alias_capabilities["vision"] = capabilities[CAPABILITY_VISION]
    entry["capabilities"] = alias_capabilities
    if model.display_name:
        entry["display_name"] = str(model.display_name)
    if model.cleared_up_to:
        entry["data_policy_class"] = model.cleared_up_to
    else:
        entry.pop("data_policy_class", None)
    categories = sorted(set(model.approved_data_categories or []))
    if categories:
        entry["approved_data_categories"] = categories
    else:
        entry.pop("approved_data_categories", None)
    return entry


def mirror_into_alias(provider: LLMProvider, model: LLMModel) -> bool:
    entries = alias_entries(provider)
    if model.model_id not in entries or not isinstance(entries[model.model_id], dict):
        return False
    _write_entry(provider, model.model_id, _governed_fields(copy.deepcopy(entries[model.model_id]), model))
    return True


def write_alias_cost(provider: LLMProvider, alias: str, cost: dict[str, Any]) -> None:
    entry = copy.deepcopy(alias_entries(provider).get(alias) or {})
    entry["cost"] = cost
    _write_entry(provider, alias, entry)


def create_alias(provider: LLMProvider, model: LLMModel) -> None:
    entry: dict[str, Any] = {"model_group": model.model_id}
    if model.context_length and model.context_length > 0:
        entry["context_limit"] = int(model.context_length)
    if model.pricing_input and model.pricing_output and model.pricing_input > 0 and model.pricing_output > 0:
        entry["cost"] = {
            "source": "catalog_pricing",
            "input_per_million_usd": model.pricing_input,
            "output_per_million_usd": model.pricing_output,
        }
    _write_entry(provider, model.model_id, _governed_fields(entry, model))


__all__ = ["alias_entries", "create_alias", "has_alias", "mirror_into_alias", "write_alias_cost"]
