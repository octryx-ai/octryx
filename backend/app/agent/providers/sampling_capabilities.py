"""Sampling capability of a model: whether it accepts an explicit temperature."""

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
    if not model_accepts_temperature(model_id, override=override):
        return None
    if target_value is not None:
        return float(target_value)
    return requested if requested is not None else default


def gateway_temperature(
    requested: float | None, *, override: bool | None = None, target_value: float | None = None
) -> float | None:
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
