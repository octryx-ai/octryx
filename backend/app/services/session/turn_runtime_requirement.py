"""The model capability a selected workflow requires of the turn's runtime (R3, W22b).

A workflow definition may declare ``required_model_capability`` on its contract. The
capability must be in the admin-editable capability catalog (``policy_lists.model_capabilities``,
seeded with ``coding``). A runtime target meets a capability when it is active and:

1. an admin tagged the target with the capability (``capability_tags``); or
2. the target carries no capability tag at all, the capability is ``coding`` and the model is
   not a weak coding family (``model_family_policy``, admin-editable). This is the seed
   behaviour for untagged targets.

A target with explicit capability tags is judged by them alone. A change workflow such as a
framework upgrade therefore never lands on a weak runtime because of an implicit default; the
requirement is configuration, never a guess from the prompt.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..policy_lists.live import live_policy_lists

REQUIRED_MODEL_CAPABILITY_KEY = "required_model_capability"


class UnsupportedModelCapabilityError(ValueError):
    """A definition declares a capability outside the catalog (a configuration error)."""


def required_model_capability(workflow_contract: dict[str, Any] | None) -> str:
    """The capability the selected workflow's contract requires, or ``""``."""
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    capability = str(contract.get(REQUIRED_MODEL_CAPABILITY_KEY) or "").strip().lower()
    if capability and capability not in live_policy_lists().model_capabilities:
        raise UnsupportedModelCapabilityError(capability)
    return capability


def _capability_tags(target: Any) -> set[str]:
    return {str(tag).strip().lower() for tag in (getattr(target, "capability_tags", None) or []) if str(tag).strip()}


def target_satisfies(target: Any, capability: str) -> bool:
    """Whether an active runtime target meets ``capability`` (no capability: always)."""
    if not bool(getattr(target, "is_active", False)):
        return False
    if not capability:
        return True
    # a capability never excludes a model (no release per kind of work); a target tagged with it is
    # only preferred (``best_target_for`` ranks it first).
    return True


def best_target_for(targets: Iterable[Any], capability: str, *, allowed: Any) -> str:
    """The highest-priority allowed target meeting ``capability``; explicitly tagged ones first."""
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
