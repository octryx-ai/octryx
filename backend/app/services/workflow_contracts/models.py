"""The code-defined workflow families a selected workflow or a workflow-run phase builds its contract from."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowPhase:
    id: str
    preferred_tools: tuple[str, ...]
    required_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "preferred_tools": list(self.preferred_tools),
        }
        # Additive-only serialization: the key appears only when a phase
        # declares criteria, so existing workflow contracts stay byte-stable.
        if self.required_tools:
            data["required_tools"] = list(self.required_tools)
        return data


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    intent_type: str
    description: str
    phases: tuple[WorkflowPhase, ...]
    matcher: Callable[..., bool]
    contract_builder: Callable[..., dict[str, Any]]
    planner: Callable[..., list[dict[str, Any]]]
