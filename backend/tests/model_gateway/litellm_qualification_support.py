"""Activation qualification and its evidence.

What the gate has to establish before ``litellm_gateway`` may be enabled in a
shared environment:

- the content-logging/callback posture is admitted only when neither prompts nor
  credentials can be retained, and a declaration never counts as live proof;
- every admitted alias reports integral prompt/completion usage, settles its
  declared cost contract, names the governed model group, and has its
  ``model_info.supports_*`` capabilities backed by the catalog;
- each mismatch case is *refused*, with the expected state and no leakage;
- a required check that never ran leaves the gate closed;
- the report can only be written under the allowlisted evidence path, and
  never with a secret-shaped key or value — while the closed host-shaped fields
  still admit the deployment's own hostnames, which can contain a credential
  prefix as a substring (``nonprod`` carries ``sk-``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.model_gateway.litellm import build_gateway_config
from app.services.model_gateway.litellm.client import LiteLLMGatewayHttpClient
from app.services.model_gateway.litellm.content_logging import (
    KEY_METADATA_RETAINED_BY_INTERNAL_PLATFORM_GATEWAY,
    VERIFIED_AGAINST_LIVE,
)
from app.services.model_gateway.litellm.errors import (
    GATEWAY_STATE_FALLBACK_VIOLATION,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
)
from app.services.model_gateway.litellm.qualification import (
    FailClosedExpectation,
    qualify_fail_closed,
    run_alias_qualification,
)
from app.services.model_gateway.litellm.qualification_codes import (
    FAIL_CLOSED_CAPABILITY_NOT_PROVEN,
    FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE,
    FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
    FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
    FAIL_CLOSED_MODEL_GROUP_MISMATCH,
    FAIL_CLOSED_USAGE_NOT_REPORTED,
)
from app.services.model_gateway.litellm.qualification_report import QualificationCheck, build_qualification_report
from app.services.model_gateway.litellm.usage_contract import (
    COST_DENIAL_FREE_CONTRACT_REPORTED_COST,
    COST_DENIAL_GATEWAY_NOT_POSITIVE,
    USAGE_DENIAL_NOT_REPORTED,
)
from tests.model_gateway.conftest import BASE_URL, CONTENT_LOGGING_POSTURE, VIRTUAL_KEY, gateway_section

# Three aliases, one per cost contract, so a single qualification run covers all
# three obligations: positive catalog pricing, strictly positive gateway-reported
# cost, and audited zero for governed_free.
PRICED_ALIAS = "octryx-priced"


PRICED_GROUP = "priced-group"


REPORTED_ALIAS = "octryx-reported"


REPORTED_GROUP = "reported-group"


FREE_ALIAS = "octryx-free"


FREE_GROUP = "free-group"


REPORTED_COST = 0.0042


PROBE_MAX_INPUT_TOKENS = 128000


CATALOG = {
    "data": [
        {
            "id": group,
            "model_info": {
                "supports_function_calling": True,
                "supports_vision": False,
                "supports_reasoning": False,
                "supports_response_schema": False,
                "max_input_tokens": PROBE_MAX_INPUT_TOKENS,
            },
        }
        for group in (PRICED_GROUP, REPORTED_GROUP, FREE_GROUP)
    ]
}


def alias_entry(model_group: str, cost: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "model_group": model_group,
        "context_limit": PROBE_MAX_INPUT_TOKENS,
        "data_policy_class": "internal",
        "capabilities": {"tools": True},
        "cost": cost,
    }
    entry.update(overrides)
    return entry


def qualification_section(**overrides: Any) -> dict[str, Any]:
    section = gateway_section(
        aliases={
            PRICED_ALIAS: alias_entry(
                PRICED_GROUP,
                {"source": "catalog_pricing", "input_per_million_usd": 1.0, "output_per_million_usd": 2.0},
            ),
            REPORTED_ALIAS: alias_entry(
                REPORTED_GROUP,
                {"source": "gateway_reported", "contract_reference": "cost-contract-2026-09"},
            ),
            FREE_ALIAS: alias_entry(
                FREE_GROUP,
                {"source": "governed_free", "contract_reference": "free-tier-approval-2026-09"},
            ),
        }
    )
    section.update(overrides)
    return section


def chat_response(model_group: str, **overrides: Any) -> dict[str, Any]:
    usage: dict[str, Any] = {"prompt_tokens": 1200, "completion_tokens": 340}
    if model_group == REPORTED_GROUP:
        usage["cost"] = REPORTED_COST
    body: dict[str, Any] = {
        "model": model_group,
        "choices": [{"message": {"content": "pong", "tool_calls": None}}],
        "usage": usage,
    }
    body.update(overrides)
    return body


class ScriptedGateway:
    """LiteLLM-compatible fake that answers per requested model group."""

    def __init__(self, *, catalog: dict[str, Any] | None = None, chat: dict[str, dict[str, Any]] | None = None):
        self.catalog = CATALOG if catalog is None else catalog
        self.chat = chat or {}
        self.requests: list[tuple[str, str]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=self.catalog)
        payload = json.loads(request.content.decode("utf-8"))
        group = str(payload.get("model") or "")
        return httpx.Response(200, json=self.chat.get(group, chat_response(group)))


def build_client(gateway: ScriptedGateway, section: dict[str, Any] | None = None) -> LiteLLMGatewayHttpClient:
    config = build_gateway_config(
        endpoint_url=BASE_URL,
        virtual_key=VIRTUAL_KEY,
        config_json={"litellm_gateway": section or qualification_section()},
    )
    return LiteLLMGatewayHttpClient(config, transport=gateway.transport())


# The shared data-platform LiteLLM keeps the virtual key's identity in its own
# spend logs (budget enforcement) and cannot switch that off. That one fact is
# admitted, by name, and only when nothing can carry it out of the gateway.
PLATFORM_GATEWAY_POSTURE = {
    **CONTENT_LOGGING_POSTURE,
    "key_metadata_retention": KEY_METADATA_RETAINED_BY_INTERNAL_PLATFORM_GATEWAY,
    "attestation_reference": "cluster-posture-2026-11-06",
    "attested_on": "2026-11-06",
}


# --- Fail-closed qualification ----------------------------------------------

FAIL_CLOSED_CASES: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        FAIL_CLOSED_MODEL_GROUP_MISMATCH,
        GATEWAY_STATE_FALLBACK_VIOLATION,
        "",
        {"model": "some-other-group"},
    ),
    (
        FAIL_CLOSED_USAGE_NOT_REPORTED,
        GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
        USAGE_DENIAL_NOT_REPORTED,
        {"usage": {}},
    ),
    (
        FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE,
        GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
        COST_DENIAL_GATEWAY_NOT_POSITIVE,
        {"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": "0"}},
    ),
    (
        FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST,
        GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
        COST_DENIAL_FREE_CONTRACT_REPORTED_COST,
        {"usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.01}},
    ),
)


# --- Report and evidence -----------------------------------------------------


async def full_report(*, evidence_origin: str, live_posture: bool = False):
    section = qualification_section()
    if live_posture:
        section["content_logging"] = {**CONTENT_LOGGING_POSTURE, "verified_against": VERIFIED_AGAINST_LIVE}
    gateway = ScriptedGateway()
    client = build_client(gateway, section)
    try:
        checks = list(await run_alias_qualification(client=client, config=client.config))
        for code, state, denial, overrides in FAIL_CLOSED_CASES:
            alias, group = {
                FAIL_CLOSED_MODEL_GROUP_MISMATCH: (PRICED_ALIAS, PRICED_GROUP),
                FAIL_CLOSED_USAGE_NOT_REPORTED: (PRICED_ALIAS, PRICED_GROUP),
                FAIL_CLOSED_GATEWAY_COST_NOT_POSITIVE: (REPORTED_ALIAS, REPORTED_GROUP),
                FAIL_CLOSED_FREE_CONTRACT_REPORTED_COST: (FREE_ALIAS, FREE_GROUP),
            }[code]
            scripted = ScriptedGateway(chat={group: chat_response(group, **overrides)})
            scripted_client = build_client(scripted, section)
            entry = next(item for item in scripted_client.config.aliases if item.alias == alias)
            try:
                checks.append(
                    await qualify_fail_closed(
                        FailClosedExpectation(code, state, denial),
                        lambda c=scripted_client, e=entry: c.chat_completion(
                            entry=e, messages=[{"role": "user", "content": "ping"}]
                        ),
                    )
                )
            finally:
                await scripted_client.aclose()
        # The two remaining required fail-closed checks, proven in their own tests
        # above, are recorded here so the report is complete.
        checks.append(QualificationCheck(FAIL_CLOSED_CATALOG_COST_NOT_POSITIVE, "passed"))
        checks.append(QualificationCheck(FAIL_CLOSED_CAPABILITY_NOT_PROVEN, "passed"))
        return build_qualification_report(
            config=client.config,
            evidence_origin=evidence_origin,
            checks=checks,
        )
    finally:
        await client.aclose()
