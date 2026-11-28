"""The seat keys of ``agent_gateway_policy``: names, defaults and validation.
Apart from ``seat_policy`` because ``policy`` validates them on every admin write."""

from __future__ import annotations

from typing import Any

SEAT_MODE_KEY = "seat_mode"
REQUIRES_GOVERNED_KEY = "requires_governed_routing"
SEAT_MODELS_KEY = "seat_models"
# Whether a seat session may also call the Workspace's company (governed) models, billed to the
# Workspace budget under the governed checks. Default false: a seat session uses the subscription only.
SEAT_ALLOWS_GOVERNED_MODELS_KEY = "seat_allows_governed_models"
# The Codex seat (a person's own ChatGPT login through ``model_gateway/inbound/codex_seat``): its own switch, the
# same values and the same classification rules as ``seat_mode``. Default forbidden.
CODEX_SEAT_MODE_KEY = "codex_seat_mode"
# The Codex models a Codex seat session may call; absent: every Codex model (Codex picks its own).
CODEX_SEAT_MODELS_KEY = "codex_seat_models"
SEAT_POLICY_KEYS = frozenset({SEAT_MODE_KEY, REQUIRES_GOVERNED_KEY, SEAT_MODELS_KEY, SEAT_ALLOWS_GOVERNED_MODELS_KEY,
                              CODEX_SEAT_MODE_KEY, CODEX_SEAT_MODELS_KEY})

SEAT_MODE_FORBIDDEN = "forbidden"
SEAT_MODE_ALLOWED = "allowed"
SEAT_MODES = frozenset({SEAT_MODE_FORBIDDEN, SEAT_MODE_ALLOWED})


def _baseline() -> tuple[str, ...]:
    import json
    from pathlib import Path

    from .engine_keys import ENGINE_CLAUDE_CODE
    from .review_keys import DEFAULT_MODELS

    seats = json.loads((Path(__file__).parents[1] / "workflow_runs" / "octryx" / "seat_models.json").read_text(
        encoding="utf-8"))
    # One source with the model data: every default model, the reviewer's included, is admitted.
    models = [*(seats.get("seat_baseline_also") or []), *dict(seats.get("installation_defaults") or {}).values(),
              DEFAULT_MODELS[ENGINE_CLAUDE_CODE]]
    return tuple(dict.fromkeys(str(model) for model in models if str(model).startswith("claude-")))


BASELINE_SEAT_MODELS = _baseline()
MAX_SEAT_MODELS = 20
MAX_MODEL_ID_CHARS = 100

REASON_SEAT_MODE_FORBIDDEN = "seat_mode_forbidden"
REASON_CODEX_SEAT_MODE_FORBIDDEN = "codex_seat_mode_forbidden"
REASON_SEAT_REQUIRES_GOVERNED = "seat_requires_governed_routing"
REASON_SEAT_CLASSIFICATION = "seat_classification_too_sensitive"
REASON_SEAT_CLASSIFICATION_UNRESOLVED = "seat_classification_unresolved"
# The level's matrix rule ``requires_governed_routing``: only company models apply.
REASON_SEAT_CLASSIFICATION_REQUIRES_GOVERNED = "seat_classification_requires_governed_routing"
REASON_SEAT_POLICY_INVALID = "policy_invalid"
REASON_SEAT_MODEL_NOT_ALLOWED = "seat_model_not_allowed"
REASON_SEAT_GOVERNED_MODELS_NOT_ALLOWED = "seat_governed_models_not_allowed"


class SeatPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def _model_id(value: Any, path: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_MODEL_ID_CHARS:
        raise SeatPolicyError("invalid_model_id", path)
    if not all(ch.isalnum() or ch in "._:-[]" for ch in value):
        raise SeatPolicyError("invalid_model_id", path)
    return value


def normalize_seat_policy(policy: dict[str, Any], path: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if SEAT_MODE_KEY in policy:
        if policy[SEAT_MODE_KEY] not in SEAT_MODES:
            raise SeatPolicyError("invalid_seat_mode", f"{path}.{SEAT_MODE_KEY}")
        normalized[SEAT_MODE_KEY] = policy[SEAT_MODE_KEY]
    if CODEX_SEAT_MODE_KEY in policy:
        if policy[CODEX_SEAT_MODE_KEY] not in SEAT_MODES:
            raise SeatPolicyError("invalid_seat_mode", f"{path}.{CODEX_SEAT_MODE_KEY}")
        normalized[CODEX_SEAT_MODE_KEY] = policy[CODEX_SEAT_MODE_KEY]
    if REQUIRES_GOVERNED_KEY in policy:
        if type(policy[REQUIRES_GOVERNED_KEY]) is not bool:
            raise SeatPolicyError("invalid_flag", f"{path}.{REQUIRES_GOVERNED_KEY}")
        normalized[REQUIRES_GOVERNED_KEY] = policy[REQUIRES_GOVERNED_KEY]
    if SEAT_ALLOWS_GOVERNED_MODELS_KEY in policy:
        if type(policy[SEAT_ALLOWS_GOVERNED_MODELS_KEY]) is not bool:
            raise SeatPolicyError("invalid_flag", f"{path}.{SEAT_ALLOWS_GOVERNED_MODELS_KEY}")
        normalized[SEAT_ALLOWS_GOVERNED_MODELS_KEY] = policy[SEAT_ALLOWS_GOVERNED_MODELS_KEY]
    for key in (SEAT_MODELS_KEY, CODEX_SEAT_MODELS_KEY):
        if key in policy:
            models = policy[key]
            if not isinstance(models, list) or not models or len(models) > MAX_SEAT_MODELS:
                raise SeatPolicyError("invalid_list", f"{path}.{key}")
            normalized[key] = list(
                dict.fromkeys(_model_id(item, f"{path}.{key}[{index}]") for index, item in enumerate(models))
            )
    return normalized


__all__ = [
    "BASELINE_SEAT_MODELS",
    "CODEX_SEAT_MODELS_KEY",
    "CODEX_SEAT_MODE_KEY",
    "REASON_CODEX_SEAT_MODE_FORBIDDEN",
    "REASON_SEAT_CLASSIFICATION",
    "REASON_SEAT_CLASSIFICATION_REQUIRES_GOVERNED",
    "REASON_SEAT_CLASSIFICATION_UNRESOLVED",
    "REASON_SEAT_GOVERNED_MODELS_NOT_ALLOWED",
    "REASON_SEAT_MODEL_NOT_ALLOWED",
    "REASON_SEAT_MODE_FORBIDDEN",
    "REASON_SEAT_POLICY_INVALID",
    "REASON_SEAT_REQUIRES_GOVERNED",
    "REQUIRES_GOVERNED_KEY",
    "SEAT_ALLOWS_GOVERNED_MODELS_KEY",
    "SEAT_MODELS_KEY",
    "SEAT_MODES",
    "SEAT_MODE_ALLOWED",
    "SEAT_MODE_FORBIDDEN",
    "SEAT_MODE_KEY",
    "SEAT_POLICY_KEYS",
    "SeatPolicyError",
    "normalize_seat_policy",
]
