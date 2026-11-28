from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CoordinatorMode = Literal[
    "direct",
    "worker_delegation",
    "deterministic_workflow",
    "unknown",
]
CoordinatorControlAction = Literal["stop"]


class CoordinatorStateContract(BaseModel):
    root_session_id: str
    coordinator_mode: CoordinatorMode
    aggregate_status: str
    session_status: str
    run_status: str
    run_completion_reason: str | None = None
    child_session_ids: list[str] = Field(default_factory=list)
    delegated_session_ids: list[str] = Field(default_factory=list)
    delegation_ids: list[str] = Field(default_factory=list)
    progress_counts: dict[str, int] = Field(default_factory=dict)
    progress_ratio: float | None = None
    synthesis_ready: bool = False
    can_stop: bool = False


class CoordinatorControlRequest(BaseModel):
    action: CoordinatorControlAction


class CoordinatorControlResponse(BaseModel):
    action: CoordinatorControlAction
    contract: CoordinatorStateContract
