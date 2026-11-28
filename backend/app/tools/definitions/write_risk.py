"""Closed tables of tool definitions whose canonical risk is ``write``."""

from __future__ import annotations

# Connector-owned external writes: ``deliver`` by owner type, and each needs an exact-name ``high_risk_grants`` entry.
CONNECTOR_WRITE_DEFINITION_NAMES = frozenset(
    {
        "add_confluence_comment",
        "add_issues_to_sprint",
        "add_jira_comment",
        "create_confluence_page",
        "create_jira_release_bundle",
        "create_jira_sprint",
        "create_jira_sprint_bundle",
        "create_jira_ticket",
        "create_jira_version",
        "release_jira_version",
        "transition_jira_ticket",
        "update_confluence_page",
        "update_jira_ticket",
        "commit_and_push_github_repository_branch",
        "commit_and_push_gitlab_repository_branch",
        "commit_and_push_repository_branch",
        "add_bitbucket_pull_request_comment",
        "post_bitbucket_pull_request_review",
        "post_github_pull_request_review",
        "post_gitlab_merge_request_review",
        "create_bitbucket_branch",
        "create_bitbucket_pull_request",
        "create_github_branch",
        "create_github_issue",
        "create_github_pull_request",
        "create_github_repository",
        "create_gitlab_branch",
        "create_gitlab_merge_request",
        "prepare_bitbucket_repository",
        "prepare_github_repository",
        "prepare_gitlab_repository",
        "update_bitbucket_pull_request",
        "update_github_issue",
        "update_github_pull_request",
        "update_gitlab_merge_request",
        # start/stop mutates cloud state on every provider.
        "invoke_aws_lambda",
        "start_aws_codepipeline_execution",
        "start_aws_ec2_instances",
        "start_azure_vm",
        "stop_aws_ec2_instances",
        "stop_azure_vm",
        "cancel_pipeline",
        "retry_job",
        "trigger_workflow",
        "apply",
        "rollback",
        "rollback_app",
        "run_playbook",
        "sync_app",
        "upgrade",
        # Terraform workspace select/new (``workspace new`` creates remote backend state)
        "workspace_select",
        "delete_tag",
        "renew_lease",
        "revoke_token",
        "acknowledge",
        "create_incident",
        "escalate",
        "resolve",
        "resolve_incident",
        "update_component_status",
        "update_incident",
        "create_issue",
        "create_meeting",
        "create_snapshot",
        "send_meeting_invite",
        "update_issue",
    }
)

# Every browser tool is classified here, one way or the other (``tests/tools/misc/test_browser_tool_risk.py``).
# Navigation, reading, screenshots and closing the local browser session do not change remote state.
BROWSER_READ_DEFINITION_NAMES = frozenset(
    {
        "browser_close",
        "browser_open_url",
        "browser_snapshot",
        "browser_take_screenshot",
    }
)

# Page interactions can change remote state on an external site (a click submits a form): an external write.
BROWSER_WRITE_DEFINITION_NAMES = frozenset(
    {
        "browser_click",
        "browser_press",
        "browser_type",
    }
)

# Outward-facing messages to a person outside the session (a Teams direct message). Every send needs a
# person's approval bound to its exact parameters, whatever the approval policy says
# (``services/tool_approval/gate``: rule ``outbound_message``, never exempt, no standing rule).
OUTBOUND_MESSAGE_DEFINITION_NAMES = frozenset(
    {
        "ask_reporter_via_teams",
    }
)

# Built-in-owned tools that write to an external system. They leave the platform
# boundary, so their capability requirement is ``deliver``. Connector-owned external
# writes are in ``CONNECTOR_WRITE_DEFINITION_NAMES`` and need ``deliver`` by owner type.
BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES = frozenset(
    {
        *BROWSER_WRITE_DEFINITION_NAMES,
        *OUTBOUND_MESSAGE_DEFINITION_NAMES,
    }
)

# Platform administration writes: they change the local user store from the LDAP
# directory. The LDAP connector owns them (``connector_ownership.py``), so they also
# need a high-risk grant; their capability requirement is ``deliver``.
PLATFORM_ADMIN_WRITE_DEFINITION_NAMES = frozenset(
    {
        "sync_users",
        "user_provisioning",
    }
)

# Built-in-owned writes that stay inside the platform or the session workspace.
BUILT_IN_INTERNAL_WRITE_DEFINITION_NAMES = frozenset(
    {
        "apply_patch_workspace",
        "bootstrap_workspace_repository",
        "cancel_runtime_process",
        # Git worktrees, commits and merges in the workflow run's working copy.
        "edit_workspace_file",
        # Writes the session's episode as a Workspace Knowledge source revision (needs ``change``).
        "knowledge_episode_summary",
        "memory_remember",
        "multi_edit_workspace_file",
        "run_cli_command",
        "run_saved_python_script",
        "save_python_script",
        "start_runtime_process",
        "work_item_create",
        "work_item_link_session",
        "work_item_note",
        # The client's work-item lifecycle in the chat: platform-owned state.
        "change_plan_decide",
        "change_plan_generate",
        "change_units_plan",
        "coding_agent_start",
        "work_item_redeclare",
        "work_item_transition",
        # Coordination between agents, the chat as its own agent: platform-owned state.
        "board_ack",
        "board_post",
        "work_item_claim",
        "work_item_handoff_write",
        "work_item_release",
        "work_item_takeover_request",
        # The client's run steering in the chat: the run's own rules decide; confirmed per call.
        "workflow_action_request",
        "workflow_decide",
        "workflow_select",
        # Rating an answer like the chat's thumbs: session feedback, platform state.
        "knowledge_feedback",
        "write_workspace_file",
    }
)

WRITE_RISK_DEFINITION_NAMES = frozenset(
    {
        *CONNECTOR_WRITE_DEFINITION_NAMES,
        *BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES,
        *PLATFORM_ADMIN_WRITE_DEFINITION_NAMES,
        *BUILT_IN_INTERNAL_WRITE_DEFINITION_NAMES,
    }
)

__all__ = [
    "BROWSER_READ_DEFINITION_NAMES",
    "BROWSER_WRITE_DEFINITION_NAMES",
    "BUILT_IN_EXTERNAL_WRITE_DEFINITION_NAMES",
    "BUILT_IN_INTERNAL_WRITE_DEFINITION_NAMES",
    "CONNECTOR_WRITE_DEFINITION_NAMES",
    "OUTBOUND_MESSAGE_DEFINITION_NAMES",
    "PLATFORM_ADMIN_WRITE_DEFINITION_NAMES",
    "WRITE_RISK_DEFINITION_NAMES",
]
