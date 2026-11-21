"""Closed call evidence for the governed LiteLLM gateway client.

Evidence is *built* from an allowlist of known-safe fields rather than filtered
out of a larger payload: a filter fails open when the upstream adds a field,
an allowlist fails closed. Nothing here accepts a response body, a header
value, a prompt fragment, or a transport string.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .alias_catalog import AliasEntry
from .config import LiteLLMGatewayConfig

# Every key a gateway evidence payload may ever contain.
CALL_EVIDENCE_KEYS = (
    "gateway",
    "gateway_state",
    "denial_reason",
    "status_code",
    "alias",
    "project_admission_source",
    # Which registered dispatch owner resolved the admission, and how many
    # Workspaces its scope covered. Both are closed vocabulary/counts: an owner
    # key comes from ``dispatch_owners.DISPATCH_OWNERS`` and a scope size is an
    # integer, so neither can carry config, policy contents, or a secret.
    "dispatch_owner",
    "project_scope_size",
    "model_group",
    "model_group_verified",
    "data_policy_class",
    "workspace_data_classification",
    "workspace_data_classification_source",
    "context_limit",
    "requested_capabilities",
    "proven_capabilities",
    "cost_source",
    "cost_contract_reference",
    "cost_input_per_million_usd",
    "cost_output_per_million_usd",
    "endpoint_scheme",
    "endpoint_host",
    "endpoint_port",
    "endpoint_base_path",
    "endpoint_loopback",
    "endpoint_cluster_internal",
    "probe_models_path",
    "probe_response_shape",
    "probe_model_group_field",
    "tls_mode",
    "tls_ca_bundle_certificate_count",
    "tls_ca_bundle_sha256",
    # ``plaintext_cluster_internal`` only: the operator's node-encryption
    # attestation that stands in for a TLS chain on that hop.
    "tls_node_encryption",
    "tls_attestation_reference",
    "tls_attested_on",
    "proxy_mode",
    "proxy_scheme",
    "proxy_host",
    "proxy_port",
    "proxy_tls_trust_source",
    "content_logging_mode",
    "content_logging_prompt_retention",
    "content_logging_response_retention",
    "content_logging_key_metadata_retention",
    "content_logging_header_retention",
    "content_logging_callbacks",
    "content_logging_attestation_reference",
    "content_logging_attested_on",
    "content_logging_verified_against",
    "network_path_direction",
    "network_path_hops",
    "network_path_allowed_methods",
    "network_path_allowed_request_paths",
    "network_path_follows_redirects",
    "network_path_trusts_ambient_environment",
    "admitted_alias_count",
    "request_timeout_seconds",
    "duration_ms",
)
_CALL_EVIDENCE_KEYS = frozenset(CALL_EVIDENCE_KEYS)

GATEWAY_EVIDENCE_LABEL = "litellm_gateway"


def close_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop anything outside the closed evidence allowlist."""

    return {key: value for key, value in payload.items() if key in _CALL_EVIDENCE_KEYS}


def build_call_evidence(
    *,
    config: LiteLLMGatewayConfig,
    entry: AliasEntry | None = None,
    gateway_state: str = "",
    denial_reason: str = "",
    status_code: int | None = None,
    model_group_verified: bool | None = None,
    proven_capabilities: frozenset[str] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"gateway": GATEWAY_EVIDENCE_LABEL, **config.evidence()}
    if entry is not None:
        payload.update(entry.evidence())
    if gateway_state:
        payload["gateway_state"] = gateway_state
    if denial_reason:
        payload["denial_reason"] = denial_reason
    if status_code is not None:
        payload["status_code"] = int(status_code)
    if model_group_verified is not None:
        payload["model_group_verified"] = bool(model_group_verified)
    if proven_capabilities is not None:
        payload["proven_capabilities"] = sorted(proven_capabilities)
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    return close_evidence(payload)


def build_denial_evidence(
    *,
    gateway_state: str,
    denial_reason: str = "",
    alias: str = "",
    project_admission_source: str = "",
    dispatch_owner: str = "",
    project_scope_size: int | None = None,
    data_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evidence for a denial raised before a config or client could be built.

    ``data_policy`` is the closed decision payload from
    ``services/model_gateway/data_policy`` (workspace classification, its source,
    and the alias class). It is merged through the same allowlist as everything
    else, so a producer cannot widen the payload by passing extra keys.
    """

    payload: dict[str, Any] = {"gateway": GATEWAY_EVIDENCE_LABEL, "gateway_state": gateway_state}
    if denial_reason:
        payload["denial_reason"] = denial_reason
    if alias:
        payload["alias"] = alias
    if project_admission_source:
        payload["project_admission_source"] = project_admission_source
    if dispatch_owner:
        payload["dispatch_owner"] = dispatch_owner
    if project_scope_size is not None:
        payload["project_scope_size"] = int(project_scope_size)
    if isinstance(data_policy, Mapping):
        payload.update({key: value for key, value in data_policy.items() if value not in (None, "")})
    return close_evidence(payload)


__all__ = [
    "CALL_EVIDENCE_KEYS",
    "GATEWAY_EVIDENCE_LABEL",
    "build_call_evidence",
    "build_denial_evidence",
    "close_evidence",
]
