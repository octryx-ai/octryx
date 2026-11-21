"""A gateway alias whose upstream model rejects a temperature is warned about.

The gateway applies no sampling catalog over aliases, so a model's catalog temperature is sent as set. Where the
provider's alias catalog names the upstream model (``model_group`` / ``served_model_ids``), the runtime row carries
``temperature_warning``.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.control_plane.runtime_temperature import (
    gateway_alias_rejecting_model,
    serialize_target_temperature,
)


def _alias(model_group: str, served: list[str] | None = None) -> dict:
    entry = {
        "model_group": model_group,
        "context_limit": 200000,
        "data_policy_class": "internal",
        "capabilities": {"tools": True, "structured_output": False, "reasoning": False, "vision": False},
        "cost": {"source": "catalog_pricing", "input_per_million_usd": 3.0, "output_per_million_usd": 15.0},
    }
    if served is not None:
        entry["served_model_ids"] = served
    return entry


GATEWAY = SimpleNamespace(
    name="gateway", driver="litellm_gateway", auth_mode=None,
    config_json={"litellm_gateway": {"aliases": {
        "chat-new": _alias("bedrock/eu.anthropic.claude-opus-5-5"),
        "chat-old": _alias("anthropic/claude-sonnet-4-5"),
        "chat-served": _alias("group-a", served=["model-x", "claude-sonnet-5"]),
    }}},
)
# The same alias catalog on a direct Bedrock provider: the driver alone keeps the warning away.
BEDROCK = SimpleNamespace(name="bedrock", driver="bedrock_api", auth_mode=None, config_json=GATEWAY.config_json)


def _target(model_id: str, *, accepts: bool | None = None):
    return SimpleNamespace(model_id=model_id, accepts_temperature=accepts)


def test_an_alias_routed_to_a_rejecting_model_is_named() -> None:
    assert gateway_alias_rejecting_model(_target("chat-new"), GATEWAY) == "bedrock/eu.anthropic.claude-opus-5-5"
    assert gateway_alias_rejecting_model(_target("chat-served"), GATEWAY) == "claude-sonnet-5"
    assert gateway_alias_rejecting_model(_target("chat-old"), GATEWAY) is None, "accepts a temperature"
    assert gateway_alias_rejecting_model(_target("not-listed"), GATEWAY) is None, "unknown: no guess"


def test_the_row_warns_for_such_an_alias() -> None:
    model = SimpleNamespace(temperature=0.5)
    warning = serialize_target_temperature(_target("chat-new"), GATEWAY, model)["temperature_warning"]
    assert "claude-opus-5-5" in warning and "rejects an explicit temperature" in warning
    assert serialize_target_temperature(_target("chat-new"), GATEWAY)["temperature_warning"], (
        "shown before the model has a value, so setting one is warned about"
    )


def test_no_warning_where_the_admin_stated_the_support_or_the_driver_applies_the_catalog() -> None:
    assert serialize_target_temperature(_target("chat-old"), GATEWAY)["temperature_warning"] is None
    assert serialize_target_temperature(_target("chat-new", accepts=True), GATEWAY)["temperature_warning"] is None
    assert serialize_target_temperature(_target("chat-new", accepts=False), GATEWAY)["temperature_warning"] is None
    # Direct Bedrock applies the sampling catalog itself.
    assert serialize_target_temperature(_target("chat-new"), BEDROCK)["temperature_warning"] is None
