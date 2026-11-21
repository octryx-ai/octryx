"""Fallback mode resolution, the readiness contract that keeps a provider non-runnable until complete, and the driver registration."""

from __future__ import annotations

from typing import Any

from app.agent.core.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
from app.agent.engine.runtime._engine_runtime_retry_policy import build_runtime_retry_policy
from app.agent.providers.provider_registry import get_driver_spec
from app.services.model_gateway.litellm import apply_model_policy_to_runtimes
from app.services.provider import READINESS_NEEDS_CONFIGURATION, READINESS_UNKNOWN, resolve_provider_readiness
from tests.model_gateway.conftest import PROJECT_ID, backup_runtime, gateway_config, gateway_provider, gateway_runtime

# Readiness contract: a gateway provider stays non-runnable until endpoint,
# virtual-key reference, alias catalog, and probe contract are all complete.
READINESS_DENIALS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("no alias catalog", {"config_json": {}}, "litellm_gateway_alias_catalog_missing"),
    (
        "endpoint off the allowlist",
        {"endpoint_url": "https://litellm.attacker.test/v1"},
        "litellm_gateway_endpoint_host_not_allowlisted",
    ),
    (
        "no virtual-key secret reference",
        {"api_key_secret_ref": ""},
        "litellm_gateway_virtual_key_secret_ref_not_configured",
    ),
    (
        "probe path not pinned",
        {"config_json": gateway_config(probe_contract={"models_path": "/anything"})},
        "litellm_gateway_probe_contract_path_not_pinned",
    ),
    (
        "empty alias catalog",
        {"config_json": gateway_config(aliases={})},
        "litellm_gateway_alias_catalog_has_no_admitted_alias",
    ),
    (
        "only inadmissible aliases",
        {"config_json": gateway_config(aliases={"broken": {"model_group": ""}})},
        "litellm_gateway_alias_catalog_has_no_admitted_alias",
    ),
)


def test_fallback_mode_source_is_resolved_explicitly() -> None:
    gateway_chain = [gateway_runtime()]
    other_chain = [backup_runtime()]
    invalid_setting = {"runtime_fallback_mode": "everything_everywhere"}

    gateway_default = build_runtime_retry_policy({}, runtimes=gateway_chain)
    governed = build_runtime_retry_policy(
        {"runtime_fallback_mode": RUNTIME_FALLBACK_MODE_ALL_RUNTIMES},
        runtimes=gateway_chain,
    )
    other_default = build_runtime_retry_policy({}, runtimes=other_chain)
    gateway_invalid = build_runtime_retry_policy(invalid_setting, runtimes=gateway_chain)
    other_invalid = build_runtime_retry_policy(invalid_setting, runtimes=other_chain)

    def _resolved(policy: dict[str, Any]) -> tuple[str, str]:
        return policy["fallback_mode"], policy["fallback_mode_source"]

    # Unset means "next allowed model" for every driver, the gateway too;
    # the chain is bounded by the Workspace allowlist and the data clearance, not by a per-driver default.
    assert _resolved(gateway_default) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "default")
    assert _resolved(governed) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "governed_setting")
    assert _resolved(other_default) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "default")
    # Garbage in the setting is recorded as invalid; the mode is the unset meaning.
    assert _resolved(gateway_invalid) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "invalid_setting")
    assert _resolved(other_invalid) == (RUNTIME_FALLBACK_MODE_ALL_RUNTIMES, "invalid_setting")


def test_only_the_first_dispatchable_target_decides_the_fallback_default() -> None:
    denied_gateway_first = apply_model_policy_to_runtimes(
        [gateway_runtime(), backup_runtime()],
        project_config={},
        project_id=PROJECT_ID,
    )

    policies = (
        build_runtime_retry_policy({}, runtimes=denied_gateway_first),
        build_runtime_retry_policy({}, runtimes=[backup_runtime(), gateway_runtime()]),
    )

    # A gateway that never dispatches — denied, or sitting behind another
    # runtime — must not change the fallback behavior in front of it.
    for policy in policies:
        assert policy["fallback_mode"] == RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
        assert policy["fallback_mode_source"] == "default"


def test_readiness_stays_non_runnable_until_the_contract_is_complete() -> None:
    observed: list[tuple[str, str]] = []

    for label, overrides, _expected in READINESS_DENIALS:
        readiness = resolve_provider_readiness(gateway_provider(**overrides))
        assert readiness["status"] == READINESS_NEEDS_CONFIGURATION
        assert readiness["runtime_attempt_allowed"] is False
        observed.append((label, readiness["reason"]))

    assert observed == [(label, reason) for label, _overrides, reason in READINESS_DENIALS]


def test_readiness_allows_a_runtime_attempt_once_the_contract_is_valid() -> None:
    readiness = resolve_provider_readiness(gateway_provider())

    assert readiness["status"] == READINESS_UNKNOWN
    assert readiness["runtime_attempt_allowed"] is True
    assert readiness["driver"] == "litellm_gateway"


def test_driver_is_registered_and_requires_an_endpoint() -> None:
    spec = get_driver_spec("litellm_gateway")

    assert spec is not None
    assert spec.requires_endpoint_url is True
    assert spec.provider_family == "litellm"
    # The generic OpenAI-compatible driver keeps its own behavior.
    generic = get_driver_spec("openai_compatible")
    assert generic is not None and generic.driver == "openai_compatible"
