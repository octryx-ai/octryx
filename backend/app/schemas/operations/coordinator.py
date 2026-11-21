from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CoordinatorMode = Literal[
    "direct",
    "sub_agent_group",
    "worker_delegation",
    "deterministic_workflow",
    "unknown",
]
CoordinatorControlAction = Literal["continue", "stop"]


class CoordinatorStateContract(BaseModel):
    root_session_id: str
    coordinator_mode: CoordinatorMode
    aggregate_status: str
    session_status: str
    run_status: str
    run_completion_reason: str | None = None
    child_session_ids: list[str] = Field(default_factory=list)
    delegated_session_ids: list[str] = Field(default_factory=list)
    sub_agent_group_id: str | None = None
    delegation_ids: list[str] = Field(default_factory=list)
    progress_counts: dict[str, int] = Field(default_factory=dict)
    progress_ratio: float | None = None
    document_flow: dict[str, str | int | bool | None] | None = None
    synthesis_ready: bool = False
    can_continue: bool = False
    can_stop: bool = False


class CoordinatorControlRequest(BaseModel):
    action: CoordinatorControlAction


class CoordinatorControlResponse(BaseModel):
    action: CoordinatorControlAction
    contract: CoordinatorStateContract
