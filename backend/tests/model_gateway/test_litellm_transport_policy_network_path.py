"""The governed httpx transport arguments, the derived network path, dispatch denials and readiness reporting."""

from __future__ import annotations

import ssl
from typing import Any

import httpx
import pytest

from app.services.model_gateway.litellm import LiteLLMGatewayError, build_gateway_config
from app.services.model_gateway.litellm.client import LiteLLMGatewayHttpClient
from app.services.model_gateway.litellm.content_logging import (
    CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN,
    CONTENT_LOGGING_DENIAL_CONTRACT_MISSING,
    CONTENT_LOGGING_DENIAL_HEADER_RETENTION,
    CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION,
    CONTENT_LOGGING_DENIAL_PROMPT_RETENTION,
    CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION,
)
from app.services.model_gateway.litellm.errors import GATEWAY_STATE_CONFIGURATION_INVALID
from app.services.model_gateway.litellm.network_path import (
    DIRECTION_EGRESS_ONLY,
    HOP_ROLE_DIRECT_EGRESS,
    HOP_ROLE_PROXY_EGRESS,
    HOP_ROLE_TUNNELED_DESTINATION,
    build_network_path_contract,
)
from app.services.model_gateway.litellm.readiness import gateway_configuration_reason
from app.services.model_gateway.litellm.transport_codes import (
    PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED,
    TLS_DENIAL_BUNDLE_NOT_A_FILE,
    TLS_DENIAL_BUNDLE_PATH_MISSING,
    TLS_DENIAL_CONTRACT_MISSING,
    TLS_DENIAL_MODE_UNKNOWN,
)
from tests.model_gateway.conftest import (
    BASE_URL,
    CONTENT_LOGGING_POSTURE,
    GATEWAY_HOST,
    VIRTUAL_KEY,
    gateway_config,
    gateway_provider,
    gateway_section,
)
from tests.model_gateway.litellm_transport_policy_support import PROXY_HOST, PROXY_URL, private_ca_bundle

# --- httpx construction ------------------------------------------------------


def test_the_client_constructs_httpx_with_the_governed_transport_arguments(monkeypatch, tmp_path) -> None:
    bundle = private_ca_bundle(tmp_path)
    config = build_gateway_config(
        endpoint_url=BASE_URL,
        virtual_key=VIRTUAL_KEY,
        config_json=gateway_config(
            tls={"mode": "private_ca_bundle", "ca_bundle_path": str(bundle)},
            proxy={"mode": "governed_proxy", "url": PROXY_URL, "host_allowlist": [PROXY_HOST]},
        ),
    )
    captured: dict[str, Any] = {}

    class RecordingAsyncClient:
        """Records the construction arguments; opens nothing."""

        def __init__(self, **kwargs: Any):
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)
    LiteLLMGatewayHttpClient(config)

    assert isinstance(captured["verify"], ssl.SSLContext)
    assert captured["proxy"] == PROXY_URL
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False


# --- Least-privilege network path -------------------------------------------


def test_the_direct_network_path_is_one_egress_hop() -> None:
    config = build_gateway_config(
        endpoint_url=BASE_URL,
        virtual_key=VIRTUAL_KEY,
        config_json=gateway_config(),
    )

    contract = build_network_path_contract(
        endpoint=config.endpoint,
        transport=config.transport,
        probe=config.probe,
    )

    assert contract.direction == DIRECTION_EGRESS_ONLY
    assert contract.egress_rules() == (f"{HOP_ROLE_DIRECT_EGRESS}:https:{GATEWAY_HOST}:443",)
    assert contract.allowed_methods == ("GET", "POST")
    assert contract.allowed_request_paths == ("/v1/models", "/v1/chat/completions")
    assert contract.follows_redirects is False
    assert contract.trusts_ambient_environment is False


def test_a_governed_proxy_moves_the_gateway_into_a_proxy_acl_entry() -> None:
    config = build_gateway_config(
        endpoint_url=BASE_URL,
        virtual_key=VIRTUAL_KEY,
        config_json=gateway_config(
            proxy={"mode": "governed_proxy", "url": PROXY_URL, "host_allowlist": [PROXY_HOST]},
        ),
    )

    contract = build_network_path_contract(
        endpoint=config.endpoint,
        transport=config.transport,
        probe=config.probe,
    )

    assert contract.egress_rules() == (
        f"{HOP_ROLE_PROXY_EGRESS}:https:{PROXY_HOST}:3128",
        f"{HOP_ROLE_TUNNELED_DESTINATION}:https:{GATEWAY_HOST}:443",
    )
    assert contract.evidence()["network_path_hops"] == list(contract.egress_rules())


# --- Fail-closed configuration and readiness --------------------------------


def test_a_provider_without_a_transport_contract_cannot_build_a_client() -> None:
    section = gateway_section()
    section.pop("tls")

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        build_gateway_config(
            endpoint_url=BASE_URL,
            virtual_key=VIRTUAL_KEY,
            config_json={"litellm_gateway": section},
        )

    error = excinfo.value
    assert error.gateway_state == GATEWAY_STATE_CONFIGURATION_INVALID
    assert error.denial_reason == TLS_DENIAL_CONTRACT_MISSING
    assert VIRTUAL_KEY not in str(error)


async def test_an_invalid_transport_or_posture_dispatches_nothing(gateway, build_gateway_client) -> None:
    """Both governed sections are admitted before a client exists.

    The config is what decides where the ``Authorization: Bearer <virtual key>``
    header may travel and who may retain it, so a malformed section has to be
    refused with zero requests — not on the first response.
    """

    posture_without = {key: value for key, value in CONTENT_LOGGING_POSTURE.items()}
    cases: dict[str, dict[str, Any]] = {
        TLS_DENIAL_CONTRACT_MISSING: {"tls": None},
        TLS_DENIAL_MODE_UNKNOWN: {"tls": {"mode": "whatever_openssl_finds"}},
        TLS_DENIAL_BUNDLE_PATH_MISSING: {"tls": {"mode": "private_ca_bundle"}},
        TLS_DENIAL_BUNDLE_NOT_A_FILE: {
            "tls": {"mode": "private_ca_bundle", "ca_bundle_path": "/nonexistent/oe/ca.pem"}
        },
        CONTENT_LOGGING_DENIAL_CONTRACT_MISSING: {"content_logging": None},
        CONTENT_LOGGING_DENIAL_PROMPT_RETENTION: {
            "content_logging": {**posture_without, "prompt_retention": "enabled"}
        },
        CONTENT_LOGGING_DENIAL_RESPONSE_RETENTION: {
            "content_logging": {**posture_without, "response_retention": "30d"}
        },
        CONTENT_LOGGING_DENIAL_KEY_METADATA_RETENTION: {
            "content_logging": {key: value for key, value in posture_without.items() if key != "key_metadata_retention"}
        },
        CONTENT_LOGGING_DENIAL_HEADER_RETENTION: {
            "content_logging": {**posture_without, "header_retention": "enabled"}
        },
        CONTENT_LOGGING_DENIAL_CALLBACK_MAY_RETAIN: {
            "content_logging": {**posture_without, "success_callbacks": ["langfuse"]}
        },
    }

    observed: dict[str, str] = {}
    for expected, overrides in cases.items():
        section = gateway_section()
        for key, value in overrides.items():
            if value is None:
                section.pop(key)
            else:
                section[key] = value
        with pytest.raises(LiteLLMGatewayError) as excinfo:
            build_gateway_client(gateway, config_json={"litellm_gateway": section})
        assert excinfo.value.gateway_state == GATEWAY_STATE_CONFIGURATION_INVALID
        observed[expected] = excinfo.value.denial_reason
        # Readiness reports the same code, so the admin surface and the runtime
        # boundary never disagree about why the provider cannot run.
        provider = gateway_provider(config_json={"litellm_gateway": section})
        assert gateway_configuration_reason(provider) == f"litellm_gateway_{expected}"

    assert observed == {expected: expected for expected in cases}
    assert gateway.requests == []


def test_readiness_reports_the_transport_denial_with_the_gateway_prefix() -> None:
    section = gateway_section()
    section["tls"] = {"mode": "private_ca_bundle"}
    provider = gateway_provider(config_json={"litellm_gateway": section})

    assert gateway_configuration_reason(provider) == f"litellm_gateway_{TLS_DENIAL_BUNDLE_PATH_MISSING}"


def test_readiness_reports_a_proxy_denial_with_the_gateway_prefix() -> None:
    section = gateway_section(proxy={"mode": "governed_proxy", "url": PROXY_URL})
    provider = gateway_provider(config_json={"litellm_gateway": section})

    assert gateway_configuration_reason(provider) == (
        f"litellm_gateway_{PROXY_DENIAL_HOST_ALLOWLIST_NOT_CONFIGURED}"
    )
