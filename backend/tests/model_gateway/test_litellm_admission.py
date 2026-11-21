"""Admission: nothing dispatches until endpoint, alias, and project all admit it.

Every denial in this suite must produce *zero* HTTP requests, and the virtual
key must never reach a repr, an evidence payload, an error text, or a host the
endpoint allowlist did not approve.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.core.runtime.runtime_admission_contract import RUNTIME_ADMISSION_DENIAL_KEY
from app.agent.core.runtime.runtime_errors import RUNTIME_ERROR_ALIAS_DENIED, classify_runtime_error
from app.services.model_gateway.litellm import (
    LiteLLMGatewayError,
    apply_model_policy_to_runtimes,
    resolve_alias_admission,
)
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_ALIAS_DENIED,
    GATEWAY_STATE_ENDPOINT_DENIED,
)
from tests.model_gateway.conftest import (
    ALIAS,
    GATEWAY_HOST,
    MESSAGES,
    MODEL_GROUP,
    PROJECT_ID,
    VIRTUAL_KEY,
    backup_runtime,
    gateway_config,
    gateway_runtime,
    gateway_section,
    granted_project_config,
    workspace_classification,
)

#: These tests call provider drivers directly: they run as the platform (``tests/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

# Endpoint contract: one fixed denial reason per rejected endpoint shape.
ENDPOINT_DENIALS = {
    f"https://user:pass@{GATEWAY_HOST}/v1": "endpoint_userinfo_present",
    f"https://{GATEWAY_HOST}/v1?team=alpha": "endpoint_query_present",
    f"https://{GATEWAY_HOST}/v1#frag": "endpoint_fragment_present",
    f"https://{GATEWAY_HOST}/v1/openai/deployments": "endpoint_unexpected_path",
    f"http://{GATEWAY_HOST}/v1": "endpoint_insecure_off_loopback",
    "https://litellm.attacker.test/v1": "endpoint_host_not_allowlisted",
    f"ftp://{GATEWAY_HOST}/v1": "endpoint_scheme_not_supported",
    "": "endpoint_not_configured",
}


# Alias catalog contract: an incomplete entry is never admitted, and the reason
# is a fixed audit code. ``gateway_reported`` and ``governed_free`` share the
# contract-reference requirement, so one case covers both.
ALIAS_ADMISSION_DENIALS: tuple[tuple[dict[str, Any], str], ...] = (
    ({"model_group": ""}, "alias_model_group_missing"),
    ({"context_limit": 0}, "alias_context_limit_invalid"),
    ({"data_policy_class": "secret-ish"}, "alias_data_policy_class_invalid"),
    ({"capabilities": {"telepathy": True}}, "alias_capabilities_invalid"),
    ({"cost": {}}, "alias_cost_contract_missing"),
    ({"cost": {"source": "free_because_i_said_so"}}, "alias_cost_source_unknown"),
    ({"cost": {"source": "catalog_pricing"}}, "alias_cost_pricing_invalid"),
    (
        {"cost": {"source": "catalog_pricing", "input_per_million_usd": 0, "output_per_million_usd": 0}},
        "alias_cost_pricing_not_billable",
    ),
    ({"cost": {"source": "gateway_reported"}}, "alias_cost_contract_reference_missing"),
)


def test_endpoint_denials_create_zero_requests(gateway, build_gateway_client) -> None:
    observed: dict[str, str] = {}

    for endpoint_url in ENDPOINT_DENIALS:
        with pytest.raises(LiteLLMGatewayError) as excinfo:
            build_gateway_client(gateway, endpoint_url=endpoint_url)
        assert excinfo.value.gateway_state == GATEWAY_STATE_ENDPOINT_DENIED
        observed[endpoint_url] = excinfo.value.denial_reason

    assert observed == ENDPOINT_DENIALS
    assert gateway.requests == []


def test_endpoint_host_allowlist_is_required(gateway, build_gateway_client) -> None:
    with pytest.raises(LiteLLMGatewayError) as excinfo:
        build_gateway_client(gateway, config_json=gateway_config(host_allowlist=[]))

    assert excinfo.value.denial_reason == "endpoint_host_allowlist_not_configured"
    assert gateway.requests == []


def test_loopback_http_endpoint_is_accepted_when_allowlisted(gateway, build_gateway_client) -> None:
    """A plaintext endpoint needs the matching plaintext trust mode.

    ``public_ca_bundle`` against ``http://`` is a configuration conflict, not a
    silently ignored trust store, so the loopback case has to say so explicitly.
    """

    client = build_gateway_client(
        gateway,
        endpoint_url="http://127.0.0.1:4000/v1",
        config_json=gateway_config(
            host_allowlist=["127.0.0.1"],
            tls={"mode": "plaintext_loopback"},
        ),
    )

    assert client.config.endpoint.loopback is True
    assert client.config.transport.tls.plaintext is True
    assert gateway.requests == []


def test_incomplete_alias_entries_are_not_admitted() -> None:
    observed: list[tuple[dict[str, Any], str]] = []

    for overrides, _expected in ALIAS_ADMISSION_DENIALS:
        section = gateway_section()
        section["aliases"][ALIAS].update(overrides)
        admission = resolve_alias_admission(ALIAS, {"litellm_gateway": section})
        assert admission.admitted is False
        observed.append((overrides, admission.denial_reason))

    assert observed == list(ALIAS_ADMISSION_DENIALS)


def test_alias_catalog_carrying_credential_material_is_denied(gateway, build_gateway_client) -> None:
    section = gateway_section()
    section["aliases"][ALIAS]["api_key"] = VIRTUAL_KEY

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        build_gateway_client(gateway, config_json={"litellm_gateway": section})

    assert excinfo.value.denial_reason in {
        "alias_catalog_contains_credential_material",
        "alias_catalog_has_no_admitted_alias",
    }
    assert gateway.requests == []


async def test_unlisted_alias_creates_zero_requests(gateway, build_gateway_client) -> None:
    client = build_gateway_client(gateway)

    with pytest.raises(LiteLLMGatewayError) as excinfo:
        await client.chat(MESSAGES, model="gpt-4o")

    assert excinfo.value.gateway_state == GATEWAY_STATE_ALIAS_DENIED
    assert excinfo.value.denial_reason == "alias_not_listed"
    assert classify_runtime_error(excinfo.value).error_class == RUNTIME_ERROR_ALIAS_DENIED
    assert gateway.requests == []


async def test_admitted_alias_sends_only_its_model_group(gateway, build_gateway_client) -> None:
    import json

    client = build_gateway_client(gateway)

    response = await client.chat(MESSAGES, model=ALIAS)

    assert len(gateway.chat_requests) == 1
    sent = json.loads(gateway.chat_requests[0].content)
    assert sent["model"] == MODEL_GROUP
    # The turn is attributed to the Octryx alias, never the upstream group.
    assert response["model"] == ALIAS
    assert response["content"] == "gateway answer"
    assert response["usage"]["gateway_evidence"]["model_group"] == MODEL_GROUP
    assert response["usage"]["gateway_evidence"]["model_group_verified"] is True


def test_model_policy_is_deny_by_default_and_annotates_instead_of_dropping() -> None:
    runtimes = [gateway_runtime(), backup_runtime()]

    denied = apply_model_policy_to_runtimes(
        runtimes,
        project_config={},
        project_id=PROJECT_ID,
        data_classification=workspace_classification(),
    )
    granted = apply_model_policy_to_runtimes(
        runtimes,
        project_config=granted_project_config(),
        project_id=PROJECT_ID,
        data_classification=workspace_classification(),
    )
    revoked = apply_model_policy_to_runtimes(
        runtimes,
        project_config={"model_policy": {"allowed_aliases": [ALIAS], "denied_aliases": [ALIAS]}},
        project_id=PROJECT_ID,
        data_classification=workspace_classification(),
    )

    # Denied: annotated in place, so the refusal stays visible in the chain.
    assert len(denied) == 2
    assert denied[0][RUNTIME_ADMISSION_DENIAL_KEY]["reason"] == "model_alias_not_granted_for_project"
    assert denied[0][RUNTIME_ADMISSION_DENIAL_KEY]["error_class"] == RUNTIME_ERROR_ALIAS_DENIED
    assert RUNTIME_ADMISSION_DENIAL_KEY not in denied[1]
    assert all(RUNTIME_ADMISSION_DENIAL_KEY not in runtime for runtime in granted)
    # An explicit denial wins over a grant for the same alias.
    assert revoked[0][RUNTIME_ADMISSION_DENIAL_KEY]["reason"] == "explicit_alias_denial"
