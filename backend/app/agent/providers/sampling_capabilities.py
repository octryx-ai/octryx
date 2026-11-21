"""Sampling capability of a model: whether it accepts an explicit temperature.

The chat/agent engine is deterministic: a direct provider call sends ``temperature=0`` unless the
caller sets another value. Some models reject any explicit temperature but their own default
(Claude 5 family on Bedrock: "`temperature` is deprecated for this model"), so for them the
temperature is omitted instead.

This table is the declarative evidence for that, matched over the base model id (a cross-region
profile prefix such as ``eu.`` or a provider prefix such as ``anthropic.`` names the same model).
A model that matches no rule accepts a temperature. An administrator overrides the catalog per
runtime target (``ControlPlaneRuntimeTarget.accepts_temperature``; ``None`` = use the catalog).

A model may carry an explicit temperature on its catalog row (``LLMModel.temperature``, handed to the
clients as ``target_temperature``): when the model accepts a temperature, that value is sent instead of
the caller's or the default. "Never send" is ``accepts_temperature=False`` (the same omission the
catalog applies).
"""

from __future__ import annotations

import re

DEFAULT_TEMPERATURE = 0.0

# Model families that reject an explicit temperature. Claude 5: claude-opus-5-5, claude-sonnet-5,
# claude-fable-5-1, ... (``claude-sonnet-4-5`` and ``claude-3-5-sonnet`` are not matched).
_TEMPERATURE_REJECTING_MODELS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^claude-(?:opus|sonnet|haiku|fable)-5(?:$|[-.:@])"),
)

# ``eu.anthropic.claude-...``, ``anthropic.claude-...``, ``anthropic/claude-...``: the base id counts.
_ID_PREFIX = re.compile(r"^(?:[a-z]{2,6}\.)?(?:anthropic[./])?")


def model_accepts_temperature(model_id: str, *, override: bool | None = None) -> bool:
    """True unless the catalog (or the runtime target's explicit override) says the model rejects one."""
    if override is not None:
        return bool(override)
    base = _ID_PREFIX.sub("", str(model_id or "").strip().lower(), count=1)
    return not any(pattern.match(base) for pattern in _TEMPERATURE_REJECTING_MODELS)


def sampling_temperature(
    model_id: str,
    requested: float | None,
    *,
    override: bool | None = None,
    target_value: float | None = None,
    default: float | None = DEFAULT_TEMPERATURE,
) -> float | None:
    """The temperature to send, or None for a rejecting model.

    The model's catalog value wins, then the requested one, then ``default``.
    """
    if not model_accepts_temperature(model_id, override=override):
        return None
    if target_value is not None:
        return float(target_value)
    return requested if requested is not None else default


def gateway_temperature(
    requested: float | None, *, override: bool | None = None, target_value: float | None = None
) -> float | None:
    """The gateway's rule: no catalog over aliases and no default, only an explicit choice.

    ``override=False`` (never send) omits the temperature, the model's catalog value is sent, otherwise
    only a temperature the caller set (the LiteLLM gateway never adds one on its own).
    """
    if override is False:
        return None
    if target_value is not None:
        return float(target_value)
    return requested


__all__ = [
    "DEFAULT_TEMPERATURE",
    "gateway_temperature",
    "model_accepts_temperature",
    "sampling_temperature",
]
