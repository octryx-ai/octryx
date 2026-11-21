"""Registry of project config keys and the service that owns each one."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.agent_gateway.policy_keys import AGENT_GATEWAY_POLICY_CONFIG_KEY

from ...evidence_grounding_settings import EVIDENCE_GROUNDING_POLICY_CONFIG_KEY
from ...standing_approvals.tool_rules import STANDING_TOOL_APPROVALS_CONFIG_KEY
from ...tool_approval_policy import APPROVAL_POLICY_CONFIG_KEY
from ...workflow_routing.proposal_policy import WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY


@dataclass(frozen=True, slots=True)
class ProjectConfigKeyOwner:
    key: str
    owner: str
    consumers: tuple[str, ...]
    policy_sensitive: bool
    validation: str

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["consumers"] = list(self.consumers)
        return payload


PROJECT_CONFIG_KEY_OWNERS: tuple[ProjectConfigKeyOwner, ...] = (
    ProjectConfigKeyOwner(
        key="runtime_policy",
        owner="runtime_policy_bundle",
        consumers=("runtime resolver", "tool access policy", "admin runtime policy panel"),
        policy_sensitive=True,
        validation="normalize_runtime_policy_config",
    ),
    ProjectConfigKeyOwner(
        key="tool_policy",
        owner="tool_access_policy",
        consumers=("tool catalog filtering", "tool execution policy"),
        policy_sensitive=True,
        validation="normalize_project_tool_policy",
    ),
    ProjectConfigKeyOwner(
        key="repository_bootstrap",
        owner="repository_bootstrap",
        consumers=("session startup", "source-control preparation"),
        policy_sensitive=True,
        validation="normalize_repository_bootstrap_config",
    ),
    ProjectConfigKeyOwner(
        key="repo_code_quality",
        owner="code_quality service",
        consumers=("code quality tools", "admin project quality panel"),
        policy_sensitive=False,
        validation="dict-only",
    ),
    ProjectConfigKeyOwner(
        key="connectors",
        owner="admin_project_connector_access_service",
        consumers=("connector activation", "tool visibility", "project connector limits"),
        policy_sensitive=True,
        validation="connector access service",
    ),
    ProjectConfigKeyOwner(
        key="tts",
        owner="tts service",
        consumers=("chat speech UI", "text-to-speech provider resolution"),
        policy_sensitive=False,
        validation="dict-only",
    ),
    ProjectConfigKeyOwner(
        key="stt",
        owner="stt service",
        consumers=("chat speech UI", "speech-to-text provider resolution"),
        policy_sensitive=False,
        validation="dict-only",
    ),
    ProjectConfigKeyOwner(
        key="trace_capture",
        owner="trace_events service",
        consumers=("session trace capture", "admin diagnostics"),
        policy_sensitive=True,
        validation="trace service defaults",
    ),
    ProjectConfigKeyOwner(
        key="model_policy",
        owner="model_gateway/litellm policy",
        consumers=("runtime target admission", "model gateway adapter"),
        policy_sensitive=True,
        validation="dict-only",
    ),
    ProjectConfigKeyOwner(
        key="data_policy",
        owner="model_gateway/data_policy",
        consumers=("runtime target admission", "model gateway dispatch"),
        policy_sensitive=True,
        validation="normalize_project_data_policy",
    ),
    ProjectConfigKeyOwner(
        key=AGENT_GATEWAY_POLICY_CONFIG_KEY,
        owner="agent_gateway/policy",
        consumers=("octryx-claude client policy", "agent gateway tool check", "agent gateway verification gate"),
        policy_sensitive=True,
        validation="normalize_agent_gateway_policy",
    ),
    ProjectConfigKeyOwner(
        key=WORKFLOW_PROPOSAL_POLICY_CONFIG_KEY,
        owner="workflow_routing/proposal_policy",
        consumers=("workflow proposal at turn start", "execution gate needs_confirmation"),
        policy_sensitive=True,
        validation="normalize_workflow_proposal_policy",
    ),
    ProjectConfigKeyOwner(
        key=STANDING_TOOL_APPROVALS_CONFIG_KEY,
        owner="standing_approvals/tool_rules",
        consumers=("tool approval gate", "command execution policy approval"),
        policy_sensitive=True,
        validation="normalize_standing_tool_approvals",
    ),
    ProjectConfigKeyOwner(
        key=EVIDENCE_GROUNDING_POLICY_CONFIG_KEY,
        owner="evidence_grounding_settings",
        consumers=("evidence-grounded answer contract at turn start",),
        policy_sensitive=True,
        validation="normalize_evidence_grounding_policy",
    ),
    ProjectConfigKeyOwner(
        key="mcp_policy",
        owner="mcp_access_policy",
        consumers=("MCP tool listing and calls", "MCP resources and prompts"),
        policy_sensitive=True,
        validation="normalized_mcp_policy",
    ),
    ProjectConfigKeyOwner(
        key="model_task_overrides",
        owner="model_selection/task_models (written by Workspace → Models)",
        consumers=("model resolver: task model before the platform task model",),
        policy_sensitive=True,
        validation="workspace_task_overrides (known tasks, string keys)",
    ),
    ProjectConfigKeyOwner(
        key=APPROVAL_POLICY_CONFIG_KEY,
        owner="tool_approval_policy",
        consumers=("tool approval gate (with the platform default)",),
        policy_sensitive=True,
        validation="normalized_workspace_policy",
    ),
    ProjectConfigKeyOwner(
        key="triage_routing",
        owner="workflow_runs/triage_routing",
        consumers=("triage follow-up start by type", "run start preselection (incident entry)"),
        policy_sensitive=False,
        validation="triage_routing.normalize_settings",
    ),
    ProjectConfigKeyOwner(
        key="pr_review_bot",
        owner="pr_review_bot/seat_choice",
        consumers=("review seat of a bot run (the PR author's, the broadcast)", "review seat API"),
        policy_sensitive=False,
        validation="pr_review_bot.seat_choice.set_review_seat",
    ),
    ProjectConfigKeyOwner(
        key="spec_approval",
        owner="workflow_runs/product_owner_wait",
        consumers=("spec-writing decisions gate (auto_accept product_owner)",),
        policy_sensitive=True,
        validation="product_owner_wait.normalize_spec_approval",
    ),
    ProjectConfigKeyOwner(
        key="corp_identity_profile_id",
        owner="corp_identity/workspace",
        consumers=("Spec Studio corporate direction", "corporate identity disk hygiene"),
        policy_sensitive=False,
        validation="corp_identity.workspace.normalize_workspace_profile_id",
    ),
    ProjectConfigKeyOwner(
        key="role_access_assignments",
        owner="project access service",
        consumers=("project access resolution", "admin project access panel"),
        policy_sensitive=True,
        validation="project access service",
    ),
)


def list_project_config_key_owners() -> list[dict[str, Any]]:
    return [owner.to_payload() for owner in PROJECT_CONFIG_KEY_OWNERS]
