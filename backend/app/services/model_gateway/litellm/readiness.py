"""Gateway-specific readiness evidence for the LiteLLM provider driver."""

from __future__ import annotations

from typing import Any

from .alias_catalog import (
    ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL,
    ALIAS_DENIAL_CATALOG_MISSING,
    admitted_alias_entries,
    config_contains_credential_material,
    gateway_config_section,
)
from .config import CATALOG_DENIAL_NO_ADMITTED_ALIAS, resolve_probe_contract
from .content_logging import resolve_content_logging_posture
from .endpoint import validate_gateway_endpoint
from .transport_policy import declares_cluster_internal_plaintext, resolve_transport_policy

READINESS_REASON_PREFIX = "litellm_gateway_"
READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED = f"{READINESS_REASON_PREFIX}virtual_key_secret_ref_not_configured"


def _prefixed(reason: str) -> str:
    return f"{READINESS_REASON_PREFIX}{reason}"


def gateway_configuration_reason(provider: Any) -> str:
    """Return a fixed ``needs_configuration`` reason, or "" when fully configured."""

    config_json = getattr(provider, "config_json", None)
    section = gateway_config_section(config_json)
    if section is None:
        return _prefixed(ALIAS_DENIAL_CATALOG_MISSING)
    if config_contains_credential_material(section):
        return _prefixed(ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL)

    validation = validate_gateway_endpoint(
        getattr(provider, "endpoint_url", None),
        allowed_hosts=section.get("host_allowlist"),
        cluster_internal_plaintext_declared=declares_cluster_internal_plaintext(section),
    )
    if validation.endpoint is None:
        return _prefixed(validation.denial_reason)

    if not str(getattr(provider, "api_key_secret_ref", "") or "").strip():
        return READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED

    probe, probe_denial = resolve_probe_contract(config_json)
    if probe is None:
        return _prefixed(probe_denial)

    transport = resolve_transport_policy(endpoint=validation.endpoint, section=section)
    if transport.policy is None:
        return _prefixed(transport.denial_reason)

    _, content_logging_denial = resolve_content_logging_posture(section)
    if content_logging_denial:
        return _prefixed(content_logging_denial)

    if not admitted_alias_entries(config_json):
        return _prefixed(CATALOG_DENIAL_NO_ADMITTED_ALIAS)
    return ""


__all__ = [
    "READINESS_REASON_PREFIX",
    "READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED",
    "gateway_configuration_reason",
]
