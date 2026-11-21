"""Request and response bodies of the orchestrator routes."""

from __future__ import annotations

from pydantic import BaseModel

from ...schemas.core.workspace_ref import OptionalWorkspaceId


class OrchestratorCreateRequest(BaseModel):
    session_id: str
    parent_session_id: str | None = None
    project_id: OptionalWorkspaceId = None
    pattern_type: str
    agent_definition_id: str | None = None
    flow_definition_version_id: str | None = None
    flow_node_id: str | None = None
    total_steps: int = 1
    routing_policy_json: dict | None = None
    delegation_policy_json: dict | None = None
    max_iterations: int = 3


class OrchestratorAddChildRequest(BaseModel):
    run_id: str
    child_session_id: str


class OrchestratorMergeRequest(BaseModel):
    run_id: str
    child_session_id: str
    child_output: dict
    merge_strategy: str = "append"


class OrchestratorConflictRequest(BaseModel):
    run_id: str
    conflict_key: str
    resolution: dict
    winner_session_id: str | None = None
    notes: str | None = None


class OrchestratorReviewRequest(BaseModel):
    run_id: str
    score: str
    notes: str | None = None


class OrchestratorCompleteRequest(BaseModel):
    run_id: str
    status: str = "completed"
    final_output: dict | None = None
    error: str | None = None


class OrchestratorRunResponse(BaseModel):
    id: str
    session_id: str
    parent_session_id: str | None
    project_id: str | None
    pattern_type: str
    agent_definition_id: str | None
    flow_definition_version_id: str | None
    flow_node_id: str | None
    current_step_index: int
    total_steps: int
    child_session_ids_json: list
    merged_output_json: dict
    conflict_resolutions_json: list
    reviewer_session_id: str | None
    last_review_score: str | None
    last_review_notes: str | None
    revision_count: int
    max_iterations: int
    routing_policy_json: dict
    delegation_policy_json: dict
    status: str
    last_child_id: str | None
    last_error: str | None
    completed_at: str | None
    created_at: str
    updated_at: str
