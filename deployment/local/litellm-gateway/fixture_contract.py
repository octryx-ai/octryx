"""Pinned contract for the local LiteLLM-compatible qualification fixture.

One source of truth for the fixture server, the proxy, and the smoke: the alias
catalog the product is configured with, the catalog payload the fixture serves,
and the response each scenario model group answers with.

This is a *contract* fixture: it speaks the OpenAI-compatible surface LiteLLM
exposes (``GET /v1/models`` with ``model_info.supports_*``, ``POST
/v1/chat/completions`` with ``usage`` and an optional ``usage.cost`` /
``response_cost``). It proves the product's contract, not the cluster's behavior —
the cluster remains an external gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The fixture binds and is addressed as 127.0.0.1: the server certificate carries
# it as a SAN IP, so TLS hostname verification is exercised without depending on
# how the machine resolves "localhost" on a dual-stack host.
HOST = "127.0.0.1"
ALLOWED_HOSTS = [HOST]
# Test-only virtual key. It is generated per run by ``fixture.sh`` in the real
# flow; this default exists so the module is importable on its own.
DEFAULT_VIRTUAL_KEY = "sk-local-fixture-virtual-key"

CONTEXT_LIMIT = 128000
PROBE_MAX_INPUT_TOKENS = 128000
PROMPT_TOKENS = 1200
COMPLETION_TOKENS = 340
GATEWAY_REPORTED_COST = 0.0042

CATALOG_PRICING = {
    "source": "catalog_pricing",
    "input_per_million_usd": 1.0,
    "output_per_million_usd": 2.0,
}
CATALOG_PRICING_ROUNDS_TO_ZERO = {
    "source": "catalog_pricing",
    # Both rates satisfy the gateway's strictly-positive admission rule. One served
    # token divided by one million still underflows to 0.0, which reaches the
    # independent post-dispatch computed-cost guard this scenario proves.
    "input_per_million_usd": 1e-320,
    "output_per_million_usd": 1e-320,
}
GATEWAY_REPORTED = {"source": "gateway_reported", "contract_reference": "local-fixture-cost-contract"}
GOVERNED_FREE = {"source": "governed_free", "contract_reference": "local-fixture-free-approval"}

CONTENT_LOGGING_POSTURE = {
    "mode": "no_content_retention",
    "prompt_retention": "disabled",
    "response_retention": "disabled",
    "key_metadata_retention": "disabled",
    "header_retention": "disabled",
    "success_callbacks": [],
    "failure_callbacks": [],
    "attestation_reference": "local-fixture-posture",
    "attested_on": "2026-09-27",
    # The fixture is not the cluster, so the posture can only ever be declared.
    "verified_against": "declared_configuration",
}

PROBE_CONTRACT = {
    "models_path": "/models",
    "response_shape": "openai_model_list",
    "model_group_field": "id",
}


@dataclass(frozen=True)
class Scenario:
    """One alias plus the response its model group answers with."""

    alias: str
    model_group: str
    cost: dict[str, Any]
    capabilities: dict[str, bool] = field(default_factory=lambda: {"tools": True})
    context_limit: int = CONTEXT_LIMIT
    # Catalog evidence for this group. ``None`` means the group is published with
    # an empty ``model_info``, so no capability is proven.
    model_info: dict[str, Any] | None = None
    # Response overrides applied on top of the conforming body.
    response_overrides: dict[str, Any] = field(default_factory=dict)


CONFORMING_MODEL_INFO = {
    "supports_function_calling": True,
    "supports_vision": False,
    "supports_reasoning": False,
    "supports_response_schema": False,
    "max_input_tokens": PROBE_MAX_INPUT_TOKENS,
}

# Aliases that must qualify positively.
QUALIFYING_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("octryx-fixture-priced", "fixture-priced-group", CATALOG_PRICING),
    Scenario("octryx-fixture-reported", "fixture-reported-group", GATEWAY_REPORTED),
    Scenario("octryx-fixture-free", "fixture-free-group", GOVERNED_FREE),
)

# Aliases whose served response must be refused. Each one is addressed explicitly
# by the smoke; none of them is part of the positive qualification set.
MISMATCH_MODEL_GROUP_SUBSTITUTE = "fixture-substituted-group"
FAIL_CLOSED_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "octryx-fixture-mismatch",
        "fixture-mismatch-group",
        CATALOG_PRICING,
        response_overrides={"model": MISMATCH_MODEL_GROUP_SUBSTITUTE},
    ),
    Scenario(
        "octryx-fixture-no-usage",
        "fixture-no-usage-group",
        CATALOG_PRICING,
        response_overrides={"usage": {}},
    ),
    Scenario(
        "octryx-fixture-zero-reported-cost",
        "fixture-zero-reported-cost-group",
        GATEWAY_REPORTED,
        response_overrides={"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": "0"}},
    ),
    Scenario(
        "octryx-fixture-paid-free",
        "fixture-paid-free-group",
        GOVERNED_FREE,
        response_overrides={"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01}},
    ),
    Scenario(
        "octryx-fixture-catalog-zero",
        "fixture-catalog-zero-group",
        CATALOG_PRICING_ROUNDS_TO_ZERO,
        response_overrides={"usage": {"prompt_tokens": 1, "completion_tokens": 0}},
    ),
    Scenario(
        "octryx-fixture-unproven-tools",
        "fixture-unproven-tools-group",
        CATALOG_PRICING,
        model_info={},
    ),
)

ALL_SCENARIOS: tuple[Scenario, ...] = (*QUALIFYING_SCENARIOS, *FAIL_CLOSED_SCENARIOS)


def scenario_by_alias(alias: str) -> Scenario:
    for scenario in ALL_SCENARIOS:
        if scenario.alias == alias:
            return scenario
    raise KeyError(alias)


def alias_catalog(scenarios: tuple[Scenario, ...]) -> dict[str, Any]:
    return {
        scenario.alias: {
            "model_group": scenario.model_group,
            "context_limit": scenario.context_limit,
            "data_policy_class": "internal",
            "capabilities": dict(scenario.capabilities),
            "cost": dict(scenario.cost),
        }
        for scenario in scenarios
    }


def catalog_payload() -> dict[str, Any]:
    """The ``GET /v1/models`` body, shaped like LiteLLM's OpenAI model list."""

    return {
        "data": [
            {
                "id": scenario.model_group,
                "object": "model",
                "owned_by": "octryx-fixture",
                "model_info": dict(
                    CONFORMING_MODEL_INFO if scenario.model_info is None else scenario.model_info
                ),
            }
            for scenario in ALL_SCENARIOS
        ]
    }


def chat_payload(model_group: str) -> dict[str, Any]:
    """The ``POST /v1/chat/completions`` body for one scenario model group."""

    scenario = next((item for item in ALL_SCENARIOS if item.model_group == model_group), None)
    usage: dict[str, Any] = {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": COMPLETION_TOKENS}
    if scenario is not None and scenario.cost["source"] == "gateway_reported":
        usage["cost"] = GATEWAY_REPORTED_COST
    body: dict[str, Any] = {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "model": model_group,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
        "usage": usage,
    }
    if scenario is not None:
        body.update(scenario.response_overrides)
    return body


def gateway_config_json(
    *,
    ca_bundle_path: str,
    scenarios: tuple[Scenario, ...],
    proxy_url: str = "",
    proxy_hosts: tuple[str, ...] = (),
) -> dict[str, Any]:
    """The provider ``config_json`` the product is configured with."""

    section: dict[str, Any] = {
        "host_allowlist": list(ALLOWED_HOSTS),
        "probe_contract": dict(PROBE_CONTRACT),
        "tls": {"mode": "private_ca_bundle", "ca_bundle_path": ca_bundle_path},
        "content_logging": dict(CONTENT_LOGGING_POSTURE),
        "aliases": alias_catalog(scenarios),
    }
    if proxy_url:
        section["proxy"] = {
            "mode": "governed_proxy",
            "url": proxy_url,
            "host_allowlist": list(proxy_hosts),
        }
    else:
        section["proxy"] = {"mode": "direct"}
    return {"litellm_gateway": section}


def endpoint_url(port: int) -> str:
    return f"https://{HOST}:{port}/v1"


__all__ = [
    "ALLOWED_HOSTS",
    "ALL_SCENARIOS",
    "CONTENT_LOGGING_POSTURE",
    "CONTEXT_LIMIT",
    "DEFAULT_VIRTUAL_KEY",
    "FAIL_CLOSED_SCENARIOS",
    "GATEWAY_REPORTED_COST",
    "HOST",
    "MISMATCH_MODEL_GROUP_SUBSTITUTE",
    "PROBE_MAX_INPUT_TOKENS",
    "QUALIFYING_SCENARIOS",
    "Scenario",
    "alias_catalog",
    "catalog_payload",
    "chat_payload",
    "endpoint_url",
    "gateway_config_json",
    "scenario_by_alias",
]
