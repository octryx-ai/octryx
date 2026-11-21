"""Explicit configuration for the governed LiteLLM gateway client.

The config is built only from values the caller passes in. There is no ambient
credential discovery, no environment lookup, and no gateway master key: the
virtual key arrives from the Secret Reference boundary
(``LLMProvider.api_key_secret_ref``) and is stored in a ``repr=False`` field so
it cannot leak through a dataclass repr, a log record, or a traceback frame.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .alias_catalog import (
    AliasEntry,
    admitted_alias_entries,
    gateway_config_section,
)
from .content_logging import ContentLoggingPosture, resolve_content_logging_posture
from .endpoint import GatewayEndpoint, validate_gateway_endpoint
from .errors import (
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_ENDPOINT_DENIED,
    GATEWAY_STATE_VIRTUAL_KEY_MISSING,
    LiteLLMGatewayError,
)
from .transport_decisions import TransportPolicy
from .transport_policy import declares_cluster_internal_plaintext, resolve_transport_policy

PROBE_DENIAL_CONTRACT_MISSING = "probe_contract_missing"
PROBE_DENIAL_PATH_NOT_PINNED = "probe_contract_path_not_pinned"
PROBE_DENIAL_RESPONSE_SHAPE_NOT_PINNED = "probe_contract_response_shape_not_pinned"
PROBE_DENIAL_MODEL_GROUP_FIELD_NOT_PINNED = "probe_contract_model_group_field_not_pinned"
CATALOG_DENIAL_NO_ADMITTED_ALIAS = "alias_catalog_has_no_admitted_alias"

# The live cluster's LiteLLM version and catalog response shape are unknown, so
# the shape is pinned by configuration instead of sniffed at runtime.
PROBE_PATHS = frozenset({"/models", "/model/info"})
PROBE_RESPONSE_SHAPES = frozenset({"openai_model_list"})
PROBE_MODEL_GROUP_FIELDS = frozenset({"id", "model_name"})

DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
MIN_REQUEST_TIMEOUT_SECONDS = 5.0
MAX_REQUEST_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class ProbeContract:
    models_path: str
    response_shape: str
    model_group_field: str

    def evidence(self) -> dict[str, Any]:
        return {
            "probe_models_path": self.models_path,
            "probe_response_shape": self.response_shape,
            "probe_model_group_field": self.model_group_field,
        }


@dataclass(frozen=True, slots=True)
class LiteLLMGatewayConfig:
    endpoint: GatewayEndpoint
    probe: ProbeContract
    transport: TransportPolicy
    content_logging: ContentLoggingPosture
    aliases: tuple[AliasEntry, ...]
    request_timeout_seconds: float
    raw_config: Mapping[str, Any]
    virtual_key: str = field(repr=False, default="")

    def evidence(self) -> dict[str, Any]:
        return {
            **self.endpoint.evidence(),
            **self.probe.evidence(),
            **self.transport.evidence(),
            **self.content_logging.evidence(),
            "admitted_alias_count": len(self.aliases),
            "request_timeout_seconds": self.request_timeout_seconds,
        }


def resolve_probe_contract(config_json: Any) -> tuple[ProbeContract | None, str]:
    """Resolve the pinned probe contract, or a fixed denial code."""

    section = gateway_config_section(config_json)
    raw = section.get("probe_contract") if section is not None else None
    if not isinstance(raw, Mapping):
        return None, PROBE_DENIAL_CONTRACT_MISSING
    models_path = str(raw.get("models_path") or "").strip()
    if models_path not in PROBE_PATHS:
        return None, PROBE_DENIAL_PATH_NOT_PINNED
    response_shape = str(raw.get("response_shape") or "").strip().lower()
    if response_shape not in PROBE_RESPONSE_SHAPES:
        return None, PROBE_DENIAL_RESPONSE_SHAPE_NOT_PINNED
    model_group_field = str(raw.get("model_group_field") or "").strip().lower()
    if model_group_field not in PROBE_MODEL_GROUP_FIELDS:
        return None, PROBE_DENIAL_MODEL_GROUP_FIELD_NOT_PINNED
    return ProbeContract(models_path, response_shape, model_group_field), ""


def _bounded_timeout(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_REQUEST_TIMEOUT_SECONDS
    if seconds <= 0:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS
    return max(MIN_REQUEST_TIMEOUT_SECONDS, min(seconds, MAX_REQUEST_TIMEOUT_SECONDS))


def _denied(denial_reason: str) -> LiteLLMGatewayError:
    return LiteLLMGatewayError(GATEWAY_STATE_CONFIGURATION_INVALID, denial_reason=denial_reason)


def _admitted_policies(
    config_json: Any, section: Mapping[str, Any], endpoint: GatewayEndpoint
) -> tuple[ProbeContract, TransportPolicy, ContentLoggingPosture, tuple[AliasEntry, ...]]:
    """Probe contract, transport, content logging and aliases, checked in this order; the first denial raises."""

    probe, probe_denial = resolve_probe_contract(config_json)
    if probe is None:
        raise _denied(probe_denial) from None

    # The transport trust store and the egress hop are governed configuration:
    # with httpx's ``trust_env`` switched off, this is the only way in.
    transport = resolve_transport_policy(endpoint=endpoint, section=section)
    if transport.policy is None:
        raise _denied(transport.denial_reason) from None

    # A gateway that may retain prompts or credentials is not admitted at all,
    # so no request can be sent before the posture is on record.
    content_logging, content_logging_denial = resolve_content_logging_posture(section)
    if content_logging is None:
        raise _denied(content_logging_denial) from None

    aliases = tuple(admitted_alias_entries(config_json))
    if not aliases:
        raise _denied(CATALOG_DENIAL_NO_ADMITTED_ALIAS) from None
    return probe, transport.policy, content_logging, aliases


def build_gateway_config(
    *,
    endpoint_url: Any,
    virtual_key: Any,
    config_json: Any,
    request_timeout_seconds: Any = None,
) -> LiteLLMGatewayConfig:
    """Build a validated gateway config, or raise a typed fixed-message error.

    Raised before any HTTP client exists, so a denied configuration produces
    zero requests.
    """

    section = gateway_config_section(config_json)
    if section is None:
        raise LiteLLMGatewayError(
            GATEWAY_STATE_CONFIGURATION_INVALID,
            denial_reason=PROBE_DENIAL_CONTRACT_MISSING,
        ) from None

    validation = validate_gateway_endpoint(
        endpoint_url,
        allowed_hosts=section.get("host_allowlist"),
        cluster_internal_plaintext_declared=declares_cluster_internal_plaintext(section),
    )
    if validation.endpoint is None:
        raise LiteLLMGatewayError(
            GATEWAY_STATE_ENDPOINT_DENIED,
            denial_reason=validation.denial_reason,
        ) from None

    key = virtual_key.strip() if isinstance(virtual_key, str) else ""
    if not key:
        raise LiteLLMGatewayError(GATEWAY_STATE_VIRTUAL_KEY_MISSING) from None

    probe, transport, content_logging, aliases = _admitted_policies(config_json, section, validation.endpoint)
    return LiteLLMGatewayConfig(
        endpoint=validation.endpoint,
        probe=probe,
        transport=transport,
        content_logging=content_logging,
        aliases=aliases,
        request_timeout_seconds=_bounded_timeout(
            request_timeout_seconds if request_timeout_seconds is not None else section.get("request_timeout_seconds")
        ),
        raw_config=dict(section),
        virtual_key=key,
    )


__all__ = [
    "CATALOG_DENIAL_NO_ADMITTED_ALIAS",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "PROBE_DENIAL_CONTRACT_MISSING",
    "PROBE_DENIAL_MODEL_GROUP_FIELD_NOT_PINNED",
    "PROBE_DENIAL_PATH_NOT_PINNED",
    "PROBE_DENIAL_RESPONSE_SHAPE_NOT_PINNED",
    "PROBE_MODEL_GROUP_FIELDS",
    "PROBE_PATHS",
    "PROBE_RESPONSE_SHAPES",
    "LiteLLMGatewayConfig",
    "ProbeContract",
    "build_gateway_config",
    "resolve_probe_contract",
]
