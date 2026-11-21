"""What temperature a runtime target's provider client sends, as the admin runtime view shows it.

The temperature value is set once per model on its catalog row (``LLMModel.temperature``); a runtime target only
overrides whether the model gets a temperature at all (``accepts_temperature``: ``None`` = the sampling catalog of
``agent/providers/sampling_capabilities``, ``True`` = accepts one, ``False`` = never send).

Only the drivers whose clients apply the rule (direct Bedrock, the LiteLLM gateway) are described in detail; every
other driver manages its sampling itself.
"""

from __future__ import annotations

from typing import Any

from ...agent.providers import infer_provider_runtime
from ...agent.providers.sampling_capabilities import DEFAULT_TEMPERATURE, model_accepts_temperature
from ..model_gateway.litellm.alias_catalog import resolve_alias_admission

# Effective outcome for a target: what the provider client will actually send.
EFFECTIVE_SENT = "sent"
EFFECTIVE_MODEL_DEFAULT = "model_default"
EFFECTIVE_NOT_SENT = "not_sent"
EFFECTIVE_DRIVER_MANAGED = "driver_managed"

DRIVER_BEDROCK = "bedrock_api"
DRIVER_LITELLM_GATEWAY = "litellm_gateway"
GOVERNED_TEMPERATURE_DRIVERS = frozenset({DRIVER_BEDROCK, DRIVER_LITELLM_GATEWAY})


def provider_driver(provider: Any) -> str:
    """The resolved driver key of a provider row ("" when unknown)."""
    if provider is None:
        return ""
    runtime = infer_provider_runtime(
        name=getattr(provider, "name", None),
        driver=getattr(provider, "driver", None),
        auth_mode=getattr(provider, "auth_mode", None),
    )
    return runtime["driver"]


def effective_temperature(target: Any, model_temperature: float | None, *, driver: str) -> dict[str, Any]:
    """What the provider client will send for ``target`` with its model's catalog temperature:
    ``mode``, ``value``, ``reason``, ``label``."""
    if driver not in GOVERNED_TEMPERATURE_DRIVERS:
        return _effective(EFFECTIVE_DRIVER_MANAGED, None, "driver_not_governed", "Set by the provider driver")
    override = getattr(target, "accepts_temperature", None)
    if override is False:
        return _effective(EFFECTIVE_NOT_SENT, None, "target_never_send", "Not sent (never send is set)")
    if not model_accepts_temperature(target.model_id, override=override):
        return _effective(
            EFFECTIVE_NOT_SENT, None, "model_rejects_temperature", "Not sent (the model rejects a temperature)"
        )
    if model_temperature is not None:
        value = float(model_temperature)
        return _effective(EFFECTIVE_SENT, value, "model_value", f"{value:g} (set for this model)")
    if driver == DRIVER_BEDROCK:
        return _effective(
            EFFECTIVE_SENT, DEFAULT_TEMPERATURE, "deterministic_default",
            f"{DEFAULT_TEMPERATURE:g} (deterministic default)",
        )
    return _effective(EFFECTIVE_MODEL_DEFAULT, None, "provider_default", "Model default (no temperature is sent)")


def _effective(mode: str, value: float | None, reason: str, label: str) -> dict[str, Any]:
    return {"mode": mode, "value": value, "reason": reason, "label": label}


def gateway_alias_rejecting_model(target: Any, provider: Any) -> str | None:
    """The upstream model of a gateway alias that the sampling catalog lists as rejecting a temperature.

    The gateway applies no catalog over aliases (an alias name says nothing about the model), so a model's value is
    sent as set. Where the provider's alias catalog names the upstream model (``model_group``, ``served_model_ids``),
    the admin is warned; ``None`` when unknown or when every named model accepts one.
    """
    entry = resolve_alias_admission(getattr(target, "model_id", ""), getattr(provider, "config_json", None)).entry
    if entry is None:
        return None
    for model in (entry.model_group, *sorted(entry.served_model_ids)):
        # ``bedrock/eu.anthropic.claude-...``: the part after the routing prefix names the model.
        if not model_accepts_temperature(model.rsplit("/", 1)[-1]):
            return model
    return None


def temperature_warning(target: Any, provider: Any, *, driver: str) -> str | None:
    """A warning for a gateway alias whose upstream model rejects a temperature."""
    if driver != DRIVER_LITELLM_GATEWAY or getattr(target, "accepts_temperature", None) is not None:
        return None  # an explicit "accepts" or "never send" is the admin's own statement
    model = gateway_alias_rejecting_model(target, provider)
    if model is None:
        return None
    return (
        f"This alias routes to {model}, which rejects an explicit temperature: a temperature set for the model is "
        "sent anyway and the request may be refused. Leave the model's temperature empty or choose never send."
    )


def serialize_target_temperature(target: Any, provider: Any, model: Any = None) -> dict[str, Any]:
    """The temperature fields of a runtime target's admin payload (``model``: its catalog row, if any)."""
    driver = provider_driver(provider)
    return {
        "temperature_effective": effective_temperature(target, getattr(model, "temperature", None), driver=driver),
        "temperature_warning": temperature_warning(target, provider, driver=driver),
    }


__all__ = [
    "EFFECTIVE_DRIVER_MANAGED",
    "EFFECTIVE_MODEL_DEFAULT",
    "EFFECTIVE_NOT_SENT",
    "EFFECTIVE_SENT",
    "GOVERNED_TEMPERATURE_DRIVERS",
    "effective_temperature",
    "gateway_alias_rejecting_model",
    "provider_driver",
    "serialize_target_temperature",
    "temperature_warning",
]
