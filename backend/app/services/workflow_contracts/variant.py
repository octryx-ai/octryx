"""The variant of a selected workflow family, as a closed state on its contract.

A selected workflow family can have variants: a ``knowledge_request`` answers as a lookup or as
a definition. The variant comes only from the selected definition's configured contract, never
from the prompt.

Every contract the family builder produces carries its variant under ``workflow_variant``:

- ``resolved``: the definition fixes the variant (``reason_code`` names the field that did), or
  it names none and the family runs its generic variant (``no_variant_configured``).
- ``needs_configuration``: the definition's variant fields contradict each other or name an
  unsupported value. The execution profile turns this into a ``needs_configuration`` turn
  (``execution_profile_service``) and the execution gate holds it; nothing is guessed.

This module is models-free so the execution profile can read it without importing the family
builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WORKFLOW_VARIANT_CONTRACT_KEY = "workflow_variant"
WORKFLOW_VARIANT_VERSION = "workflow_variant.v1"
# The execution profile's decision source for a variant refusal.
WORKFLOW_VARIANT_DECISION_SOURCE = "workflow_variant"

VARIANT_STATE_RESOLVED = "resolved"
VARIANT_STATE_NEEDS_CONFIGURATION = "needs_configuration"
VARIANT_STATES = frozenset({VARIANT_STATE_RESOLVED, VARIANT_STATE_NEEDS_CONFIGURATION})


@dataclass(frozen=True, slots=True)
class WorkflowVariant:
    family: str
    state: str
    reason_code: str
    variant: str = ""

    @property
    def resolved(self) -> bool:
        return self.state == VARIANT_STATE_RESOLVED

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WORKFLOW_VARIANT_VERSION,
            "family": self.family,
            "state": self.state,
            "reason_code": self.reason_code,
            "variant": self.variant or None,
        }


def unresolved_workflow_variant(workflow_contract: Any) -> dict[str, Any] | None:
    """The variant record of a contract whose variant is not resolved, or ``None``.

    A record with an unknown state counts as unresolved: an unclear variant never runs.
    """
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    record = contract.get(WORKFLOW_VARIANT_CONTRACT_KEY)
    if not isinstance(record, dict):
        return None
    if str(record.get("state") or "").strip() == VARIANT_STATE_RESOLVED:
        return None
    return dict(record)


__all__ = [
    "VARIANT_STATES",
    "VARIANT_STATE_NEEDS_CONFIGURATION",
    "VARIANT_STATE_RESOLVED",
    "WORKFLOW_VARIANT_CONTRACT_KEY",
    "WORKFLOW_VARIANT_DECISION_SOURCE",
    "WORKFLOW_VARIANT_VERSION",
    "WorkflowVariant",
    "unresolved_workflow_variant",
]
