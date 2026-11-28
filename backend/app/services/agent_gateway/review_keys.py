"""The independent reviewer's model per coding engine: keys and validation.
Free of database imports: ``policy`` validates the Workspace section on every admin write."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine_keys import ENGINE_CLAUDE_CODE, ENGINE_CODEX, ENGINES

REVIEW_KEY = "review"
ROUTE_COMPANY = "company"
ROUTE_SEAT = "seat"
ROUTES = (ROUTE_COMPANY, ROUTE_SEAT)


def _default_models() -> dict[str, str]:
    data = json.loads(Path(__file__).with_name("review_models.json").read_text(encoding="utf-8"))
    models = {str(engine): str(model) for engine, model in dict(data["default_models"]).items()}
    missing = [engine for engine in (ENGINE_CLAUDE_CODE, ENGINE_CODEX) if not models.get(engine)]
    if missing:
        raise ValueError(f"review_models.json names no default model for {', '.join(missing)}")
    return models


DEFAULT_MODELS = _default_models()
INSTALLATION_KEY = "review_defaults"
# A review of a change of at least ``min_diff_lines`` changed lines with fewer than ``min_findings`` findings or fewer
# than ``min_rationale_tokens`` output tokens is flagged "shallow" (a warning, never a verdict).
SHALLOW_DEFAULTS = {"min_diff_lines": 300, "min_findings": 1, "min_rationale_tokens": 300}
MAX_MODEL_CHARS = 200
_FIELDS = frozenset({"model", "route"})

REASON_MODEL_WRONG_FAMILY = "review_model_wrong_engine_family"
REASON_MODEL_NOT_ON_SEAT = "review_model_not_on_seat"


class ReviewPolicyError(ValueError):
    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason = reason
        self.path = path


def model_family(model: str) -> str | None:
    name = str(model or "").strip().lower()
    if name.startswith("gpt-"):
        return ENGINE_CODEX
    if name.startswith("claude-") or name in ("haiku", "sonnet", "opus"):
        return ENGINE_CLAUDE_CODE
    return None


def check_model_for_engine(model: str, engine: str, route: str | None) -> str | None:
    family = model_family(model)
    if family is not None and family != engine:
        return REASON_MODEL_WRONG_FAMILY  # never a Claude model on a Codex route or the other way round
    if route == ROUTE_SEAT and family != engine:
        return REASON_MODEL_NOT_ON_SEAT  # a seat serves only its engine's own models
    return None


def normalize_engine_choice(value: Any, path: str, engine: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ReviewPolicyError("not_an_object", path)
    unknown = sorted(set(value) - _FIELDS)
    if unknown:
        raise ReviewPolicyError("unknown_field", f"{path}.{unknown[0]}")
    normalized: dict[str, str] = {}
    if "model" in value:
        model = value["model"]
        if type(model) is not str or not model.strip() or len(model) > MAX_MODEL_CHARS or not model.isprintable():
            raise ReviewPolicyError("invalid_model", f"{path}.model")
        normalized["model"] = model.strip()
    if "route" in value:
        if value["route"] not in ROUTES:
            raise ReviewPolicyError("invalid_route", f"{path}.route")
        normalized["route"] = value["route"]
    if "model" in normalized and (reason := check_model_for_engine(normalized["model"], engine,
                                                                   normalized.get("route"))):
        raise ReviewPolicyError(reason, f"{path}.model")
    return normalized


def normalize_review_section(value: Any, path: str) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise ReviewPolicyError("not_an_object", path)
    unknown = sorted(set(value) - set(ENGINES))
    if unknown:
        raise ReviewPolicyError("unknown_engine", f"{path}.{unknown[0]}")
    return {engine: normalize_engine_choice(value[engine], f"{path}.{engine}", engine)
            for engine in ENGINES if engine in value}


def normalize_installation(value: Any, path: str = "review_defaults") -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or set(value) - {*ENGINES, "shallow"}:
        raise ReviewPolicyError("invalid_review_defaults", path)
    out: dict[str, Any] = normalize_review_section({key: item for key, item in value.items() if key != "shallow"},
                                                   path)
    if value.get("shallow") is not None:
        shallow = value["shallow"]
        if not isinstance(shallow, dict) or set(shallow) - set(SHALLOW_DEFAULTS) or any(
                type(item) is not int or not 0 <= item <= 1_000_000 for item in shallow.values()):
            raise ReviewPolicyError("invalid_shallow", f"{path}.shallow")
        out["shallow"] = dict(shallow)
    return out


__all__ = ["DEFAULT_MODELS", "INSTALLATION_KEY", "REASON_MODEL_NOT_ON_SEAT", "REASON_MODEL_WRONG_FAMILY", "REVIEW_KEY",
           "ROUTES", "ROUTE_COMPANY", "ROUTE_SEAT", "SHALLOW_DEFAULTS", "ReviewPolicyError", "check_model_for_engine",
           "model_family", "normalize_engine_choice", "normalize_installation", "normalize_review_section"]
