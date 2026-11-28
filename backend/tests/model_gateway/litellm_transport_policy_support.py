"""Shared proxy and cluster constants, CA bundle and key writers and policy resolvers for the LiteLLM transport policy tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError, build_gateway_config
from app.services.model_gateway.litellm.endpoint import validate_gateway_endpoint
from app.services.model_gateway.litellm.readiness import gateway_configuration_reason
from app.services.model_gateway.litellm.transport_policy import resolve_transport_policy
from tests.model_gateway.conftest import VIRTUAL_KEY, gateway_provider, gateway_section, write_ca_bundle

PROXY_HOST = "egress.internal.test"


PROXY_URL = f"https://{PROXY_HOST}:3128"


def private_ca_bundle(directory: Path, *, name: str = "ca.pem") -> Path:
    return write_ca_bundle(directory / name)


def resolve(endpoint_url: str, section: dict[str, Any]):
    validation = validate_gateway_endpoint(endpoint_url, allowed_hosts=section["host_allowlist"])
    assert validation.endpoint is not None
    return resolve_transport_policy(endpoint=validation.endpoint, section=section)


# One narrow widening of the plaintext rule: an ``http`` endpoint whose host is a
# fully qualified Kubernetes Service name, on the host allowlist, with the
# operator's node-encryption attestation, on the direct path only.

CLUSTER_HOST = "litellm.gateway.svc.cluster.local"


CLUSTER_URL = f"http://{CLUSTER_HOST}:4000"


CLUSTER_TLS = {
    "mode": "plaintext_cluster_internal",
    "node_encryption": "wireguard",
    "attested_on": "2026-11-06",
    "attestation_reference": "cluster-attestation-2026-11-06",
}


def cluster_section(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"host_allowlist": [CLUSTER_HOST], "tls": dict(CLUSTER_TLS)}
    values.update(overrides)
    return gateway_section(**values)


def cluster_denial(endpoint_url: str, section: dict[str, Any]) -> tuple[str, str]:
    with pytest.raises(LiteLLMGatewayError) as excinfo:
        build_gateway_config(
            endpoint_url=endpoint_url,
            virtual_key=VIRTUAL_KEY,
            config_json={"litellm_gateway": section},
        )
    error = excinfo.value
    assert VIRTUAL_KEY not in str(error)
    provider = gateway_provider(endpoint_url=endpoint_url, config_json={"litellm_gateway": section})
    assert gateway_configuration_reason(provider) == f"litellm_gateway_{error.denial_reason}"
    return error.gateway_state, error.denial_reason
