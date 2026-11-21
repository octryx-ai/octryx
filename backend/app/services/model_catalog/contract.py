"""The closed vocabulary of the Model catalog API (capabilities, statuses, issue codes, error codes)."""

from __future__ import annotations

from typing import Any

CAPABILITY_TOOLS = "tools"
CAPABILITY_VISION = "vision"
CAPABILITY_CODING = "coding"
CAPABILITY_LONG_CONTEXT = "long_context"
CAPABILITY_KEYS: tuple[str, ...] = (CAPABILITY_TOOLS, CAPABILITY_VISION, CAPABILITY_CODING, CAPABILITY_LONG_CONTEXT)

STATUS_ENABLED = "enabled"
STATUS_OFF = "off"
STATUS_NEEDS_ATTENTION = "needs_attention"

# Why a row needs attention (one or more per row).
ISSUE_NO_ALIAS = "no_alias"  # a gateway model with no alias: nobody can call it
ISSUE_ALIAS_INCOMPLETE = "alias_incomplete"  # the alias exists but its admission refuses it (``detail`` = code)
ISSUE_GONE_UPSTREAM = "gone_upstream"  # the provider no longer lists the model
ISSUE_PROVIDER_OFF = "provider_off"  # the provider connection is disabled
ISSUE_NOT_CLEARED = "not_cleared"  # enabled, but cleared for no data class
ISSUE_COST_DRIFT = "cost_drift"  # a gateway row shows prices its alias cost contract does not charge

ERROR_NOT_FOUND = "model_catalog_model_not_found"
ERROR_FIELD_UNKNOWN = "model_catalog_field_unknown"
ERROR_DISPLAY_NAME_INVALID = "model_catalog_display_name_invalid"
ERROR_CAPABILITIES_INVALID = "model_catalog_capabilities_invalid"
ERROR_CATEGORIES_INVALID = "model_catalog_approved_categories_invalid"
ERROR_TEMPERATURE_INVALID = "model_catalog_temperature_invalid"
ERROR_MAX_OUTPUT_INVALID = "model_catalog_max_output_invalid"
ERROR_CONTEXT_LENGTH_INVALID = "model_catalog_context_length_invalid"
ERROR_CONTEXT_LENGTH_GOVERNED = "model_catalog_context_length_governed"
ERROR_COST_INVALID = "model_catalog_cost_invalid"
ERROR_COST_GOVERNED = "model_catalog_cost_governed"
ERROR_NOT_GATEWAY = "model_catalog_not_a_gateway_model"
ERROR_ALIAS_EXISTS = "model_catalog_alias_exists"

MAX_DISPLAY_NAME_CHARS = 80
MIN_MAX_OUTPUT_TOKENS = 256
MIN_CONTEXT_LENGTH = 1000
MAX_CONTEXT_LENGTH = 10_000_000
MAX_TEMPERATURE = 2.0


class ModelCatalogError(ValueError):
    """A refused catalog change; ``code`` is fixed, ``status`` the HTTP status the route answers with."""

    def __init__(self, code: str, status: int = 422, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail


def capabilities_of(model: Any) -> dict[str, bool]:
    """The explicit capabilities of a row; without ``capabilities_json`` (provider sync, admin create and local
    bootstrap insert rows without it) tools and vision come from the ``supports_*`` flags."""
    stored = model.capabilities_json if isinstance(model.capabilities_json, dict) else None
    if stored is None:
        return {
            CAPABILITY_TOOLS: bool(model.supports_tools),
            CAPABILITY_VISION: bool(model.supports_vision),
            CAPABILITY_CODING: False,
            CAPABILITY_LONG_CONTEXT: False,
        }
    return {key: stored.get(key) is True for key in CAPABILITY_KEYS}

