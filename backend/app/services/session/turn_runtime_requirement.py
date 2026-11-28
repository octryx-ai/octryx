"""The model capability a selected workflow requires of the turn's runtime."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..policy_lists.live import live_policy_lists

REQUIRED_MODEL_CAPABILITY_KEY = "required_model_capability"


class UnsupportedModelCapabilityError(ValueError):
    pass


def required_model_capability(workflow_contract: dict[str, Any] | None) -> str:
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    capability = str(contract.get(REQUIRED_MODEL_CAPABILITY_KEY) or "").strip().lower()
    if capability and capability not in live_policy_lists().model_capabilities:
        raise UnsupportedModelCapabilityError(capability)
    return capability


def _capability_tags(target: Any) -> set[str]:
    return {str(tag).strip().lower() for tag in (getattr(target, "capability_tags", None) or []) if str(tag).strip()}


def target_satisfies(target: Any, capability: str) -> bool:
    if not bool(getattr(target, "is_active", False)):
        return False
    if not capability:
        return True
    # a capability never excludes a model (no release per kind of work); a target tagged with it is
    # only preferred (``best_target_for`` ranks it first).
    return True


def best_target_for(targets: Iterable[Any], capability: str, *, allowed: Any) -> str:
    candidates = [target for target in targets if target_satisfies(target, capability) and allowed(target)]
    if not candidates:
        return ""

    def rank(target: Any) -> tuple[int, int]:
        return (0 if capability in _capability_tags(target) else 1, int(getattr(target, "priority", 10_000) or 10_000))

    return str(getattr(min(candidates, key=rank), "id", "") or "").strip()


__all__ = [
    "REQUIRED_MODEL_CAPABILITY_KEY",
    "UnsupportedModelCapabilityError",
    "best_target_for",
    "required_model_capability",
    "target_satisfies",
]
