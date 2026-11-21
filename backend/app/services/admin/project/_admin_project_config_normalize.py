"""Owner normalization of each project config key before it is stored.

The keys are checked in one fixed order; the checks are split over two helpers only
to keep each one short, and a key no helper owns is stored as given.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY, AgentGatewayPolicyError
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy

from ...evidence_grounding_settings import (
    EVIDENCE_GROUNDING_POLICY_CONFIG_KEY,
    EvidenceGroundingPolicyError,
    normalize_evidence_grounding_policy,
)
from ...model_gateway.data_policy import (
    DATA_CLASSIFICATION_LEVELS,
    DATA_CLASSIFICATION_ORDER,
    DATA_POLICY_CLASSIFICATION_CLEARED_FIELD,
    DATA_POLICY_CLASSIFICATION_FIELD,
    DATA_POLICY_CONFIG_KEY,
    normalized_classification,
)
from ...repository_bootstrap import normalize_repository_bootstrap_config
from ...runtime_policy_bundle import normalize_runtime_policy_config
from ...standing_approvals.tool_rules import (
    STANDING_TOOL_APPROVALS_CONFIG_KEY,
    StandingToolApprovalError,
    normalize_standing_tool_approvals,
)
from ...tool_approval_policy import APPROVAL_POLICY_CONFIG_KEY, ToolApprovalPolicyError, normalized_workspace_policy
from ...work_item_analysis.settings import CONFIG_KEY as WORK_ITEM_ANALYSIS_CONFIG_KEY
from ...work_item_analysis.settings import AnalysisSettingsError, normalize_config_value
from ...workflow_routing.proposal_policy import (
    WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY,
    WorkflowProposalPolicyError,
    normalize_workflow_proposal_policy,
)
from ...workflow_routing.tool_policy import normalized_tool_policy, tool_policy_has_rules

_READ_ONLY_TOOL_POLICY_VALUES = {"read_only", "read-only", "readonly", "viewer"}

# Returned by a helper that does not own the key, so the next helper is asked.
_NOT_OWNED = object()


def _normalize_policy_section(key: str, value: Any) -> Any:
    if key == DATA_POLICY_CONFIG_KEY:
        return _normalize_project_data_policy(value)
    if key == AGENT_GATEWAY_POLICY_CONFIG_KEY:
        return _normalize_agent_gateway_policy(value)
    if key == WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY:
        try:
            return normalize_workflow_proposal_policy(value)
        except WorkflowProposalPolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
    if key == STANDING_TOOL_APPROVALS_CONFIG_KEY:
        try:
            return normalize_standing_tool_approvals(value)
        except StandingToolApprovalError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "message": str(error)}]}
            ) from None
    if key == EVIDENCE_GROUNDING_POLICY_CONFIG_KEY:
        try:
            return normalize_evidence_grounding_policy(value)
        except EvidenceGroundingPolicyError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "message": str(error)}]}
            ) from None
    if key == WORK_ITEM_ANALYSIS_CONFIG_KEY:
        try:
            return normalize_config_value(value)
        except AnalysisSettingsError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "field": error.field}]}
            ) from None
    if key == "triage_routing":
        from ...workflow_runs.triage_routing import RoutingSettingsError
        from ...workflow_runs.triage_routing import normalize_config_value as normalize_triage_routing

        try:
            return normalize_triage_routing(value)
        except RoutingSettingsError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "field": error.field}]}
            ) from None
    return _NOT_OWNED


def _normalize_workspace_section(key: str, value: Any) -> Any:
    if key == "mcp_policy":
        from ...mcp_access_policy import McpPolicyError, normalized_mcp_policy

        try:
            return normalized_mcp_policy(value)
        except McpPolicyError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "path": error.path}]}
            ) from None
    if key == "spec_approval":
        from ...workflow_runs.product_owner_wait import normalize_spec_approval

        try:
            return normalize_spec_approval(value)
        except ValueError as error:
            raise HTTPException(status_code=400, detail={"errors": [{"code": "spec_approval_invalid",
                                                                     "message": str(error)}]}) from None
    if key == "corp_identity_profile_id":
        from ...corp_identity.workspace import CorporateIdentityError, normalize_workspace_profile_id

        try:
            return normalize_workspace_profile_id(value)
        except CorporateIdentityError as error:
            raise HTTPException(status_code=400, detail={"errors": [{"code": error.code}]}) from None
    if key == "model_task_overrides":
        from ...model_selection.task_models import TASK_KEYS

        if not isinstance(value, dict) or set(value) - TASK_KEYS or not all(
            isinstance(item, str) and item for item in value.values()
        ):
            raise HTTPException(status_code=400, detail={"errors": [{"code": "model_task_overrides_invalid"}]})
        return dict(value)
    if key == APPROVAL_POLICY_CONFIG_KEY:
        try:
            return normalized_workspace_policy(value)
        except ToolApprovalPolicyError as error:
            raise HTTPException(
                status_code=400, detail={"errors": [{"code": error.code, "path": error.path}]}
            ) from None
    if key == "runtime_policy":
        if isinstance(value, dict) and "tool_policy" in value:
            raise HTTPException(status_code=400, detail="runtime_policy.tool_policy: set the project's tool_policy instead.")
        return normalize_runtime_policy_config(value if isinstance(value, dict) else {})
    if key == "repository_bootstrap":
        return normalize_repository_bootstrap_config(value if isinstance(value, dict) else {})
    if key == "tool_policy":
        return _normalize_project_tool_policy(value if isinstance(value, dict) else {})
    if key in {"repo_code_quality", "tts", "stt"}:
        return dict(value) if isinstance(value, dict) else {}
    return _NOT_OWNED


def _normalize_project_config_value(key: str, value: Any) -> Any:
    normalized = _normalize_policy_section(key, value)
    if normalized is not _NOT_OWNED:
        return normalized
    normalized = _normalize_workspace_section(key, value)
    if normalized is not _NOT_OWNED:
        return normalized
    return value


def _normalize_project_data_policy(value: Any) -> dict[str, Any]:
    """Validate the workspace data classification before it is persisted.

    An out-of-vocabulary value is rejected with a stable 400 rather than dropped:
    a dropped classification would leave the project silently unclassified, and
    gateway dispatch would then deny for "missing" while the operator believes
    they configured it. An absent/empty field is the explicit "not configured"
    state and stays allowed.
    """

    section = dict(value) if isinstance(value, dict) else {}
    if "overrides" in section:
        # Stricter-only Workspace overrides: the shape here, "stricter than the level" on write.
        from ...data_classification.workspace_overrides import OverrideError, shape_checked

        try:
            section["overrides"] = shape_checked(section["overrides"])
        except OverrideError as error:
            raise HTTPException(
                status_code=400, detail=f"{DATA_POLICY_CONFIG_KEY}.{error.path}: {error.code}"
            ) from None
    classification = normalized_classification(section.get(DATA_POLICY_CLASSIFICATION_FIELD))
    if not classification:
        # A stored section never holds an empty classification, so a present-but-empty field is this
        # patch clearing it: recorded explicitly, so no automatic default ever refills it.
        if DATA_POLICY_CLASSIFICATION_FIELD in section:
            section[DATA_POLICY_CLASSIFICATION_CLEARED_FIELD] = True
        section.pop(DATA_POLICY_CLASSIFICATION_FIELD, None)
        return section
    if classification not in DATA_CLASSIFICATION_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{DATA_POLICY_CONFIG_KEY}.{DATA_POLICY_CLASSIFICATION_FIELD} must be one of: "
                + ", ".join(DATA_CLASSIFICATION_ORDER)
            ),
        )
    section[DATA_POLICY_CLASSIFICATION_FIELD] = classification
    section.pop(DATA_POLICY_CLASSIFICATION_CLEARED_FIELD, None)
    return section


def _normalize_agent_gateway_policy(value: Any) -> dict[str, Any]:
    """Reject an invalid client policy with a stable 400 naming the field and a fixed reason."""

    try:
        return normalize_agent_gateway_policy(value)
    except AgentGatewayPolicyError as error:
        raise HTTPException(status_code=400, detail=f"{error.path}: {error.reason}") from None


def _normalize_project_tool_policy(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = normalized_tool_policy(policy)
    mode = str(policy.get("mode") or "").strip().lower()
    if mode in _READ_ONLY_TOOL_POLICY_VALUES:
        normalized["mode"] = mode
    if isinstance(policy.get("read_only_tools_only"), bool):
        normalized["read_only_tools_only"] = policy["read_only_tools_only"]
    if isinstance(policy.get("allow_write_tools"), bool):
        normalized["allow_write_tools"] = policy["allow_write_tools"]
    return normalized if tool_policy_has_rules(normalized) or len(normalized) > 5 else {}
