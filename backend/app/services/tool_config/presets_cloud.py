"""Cloud, infra and calendar connector presets."""

from __future__ import annotations

_tools_cache: dict[str, list[dict[str, str]]] = {}

KNOWLEDGE_IMPORT_FIELDS = [
    "knowledge_import_enabled",
    "knowledge_import_profile",
    "knowledge_import_frequency",
    "knowledge_import_scope",
    "knowledge_import_limits",
    "knowledge_import_retention",
]


def _auto_discover_tools(keyword: str) -> list[dict[str, str]]:
    """Auto-discover tools for a connector from the definitions registry.

    Returns list of {"name": ..., "description": ...} for all tools
    whose name contains the keyword.  Results are cached.
    """
    if keyword in _tools_cache:
        return _tools_cache[keyword]

    from ...tools.definitions.connectors import get_connectors_definitions

    defs = get_connectors_definitions()
    tools = []
    for tool_name, tool_def in sorted(defs.items()):
        if keyword in tool_name:
            func = tool_def.get("function", {})
            tools.append({
                "name": tool_name,
                "description": func.get("description", tool_name),
            })
    _tools_cache[keyword] = tools
    return tools


TOOL_CONFIG_PRESETS_CLOUD = {
    "aws": {
        "label": "AWS",
        "description": "AWS account and role configuration for cloud diagnostics and operations.",
        "fields": [
            "aws_region",
            "aws_account_id",
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
            "aws_role_arn",
            "aws_profile",
            "allow_platform_credentials",
            "aws_allowed_services",
            "aws_web_url",
            *KNOWLEDGE_IMPORT_FIELDS,
        ],
        "secret_fields": ["aws_access_key_id", "aws_secret_access_key", "aws_session_token"],
        "tools": _auto_discover_tools("aws"),
        "example": {
            "aws_region": "eu-central-1",
            # The account this entry reaches: a call naming this account_id runs on this entry.
            "aws_account_id": "123456789012",
            "aws_access_key_id": "",
            "aws_secret_access_key": "",
            "aws_session_token": "",
            "aws_role_arn": "arn:aws:iam::123456789012:role/OctryxReadOnly",
            "aws_profile": "sample-prod",
            # Admin opt-in: over MCP, use the platform host's AWS credentials when the entry has none of its own.
            "allow_platform_credentials": False,
            "aws_allowed_services": [],
            # The console base for the account's partition and region; optional, enables source links.
            "aws_web_url": "https://eu-central-1.console.aws.amazon.com",
            "knowledge_import_enabled": False,
            "knowledge_import_profile": "aws_topology",
            "knowledge_import_frequency": "hourly",
            "knowledge_import_scope": {
                "services": ["sts", "ec2", "elbv2", "eks", "rds", "lambda", "s3"],
            },
            "knowledge_import_limits": {
                "max_items": 50,
                "max_nodes": 300,
                "detail_node_limit": 50,
                "detail_edge_limit": 100,
            },
            "knowledge_import_retention": {"replace_snapshot": True},
        },
    },
    "azure": {
        "label": "Azure",
        "description": "Azure tenant and subscription access for VM operations, Monitor alerts/metrics, AKS and Cost Management.",
        "fields": [
            "azure_tenant_id",
            "azure_client_id",
            "azure_client_secret",
            "azure_subscription_ids",
            "azure_web_url",
        ],
        "secret_fields": ["azure_client_secret"],
        "tools": _auto_discover_tools("azure"),
        "example": {
            "azure_tenant_id": "tenant-id",
            "azure_client_id": "client-id",
            "azure_client_secret": "client-secret",
            "azure_subscription_ids": ["sub-prod", "sub-shared"],
            # The portal base, with the tenant (#@tenant); optional, enables source links.
            "azure_web_url": "https://portal.azure.com/#@sample.onmicrosoft.com",
        },
    },
    "gcp": {
        "label": "GCP",
        "description": "Google Cloud project and service account configuration for Compute Engine, Cloud SQL, Cloud Run, Logging, Monitoring and GKE workflows.",
        "fields": [
            "gcp_project_id",
            "gcp_region",
            "gcp_service_account_json",
            "gcp_access_token",
            "gcp_allowed_services",
            "gcp_web_url",
        ],
        "secret_fields": ["gcp_service_account_json", "gcp_access_token"],
        "tools": _auto_discover_tools("gcp"),
        "example": {
            "gcp_project_id": "sample-prod",
            "gcp_region": "europe-west3",
            "gcp_service_account_json": '{"type":"service_account"}',
            "gcp_allowed_services": [],
            # The console base; links add ?project=; optional, enables source links.
            "gcp_web_url": "https://console.cloud.google.com",
        },
    },
    "argocd": {
        "label": "ArgoCD",
        "description": "ArgoCD API endpoint and token for deployment status, sync and rollback operations.",
        "fields": ["argocd_url", "argocd_token", "argocd_allowed_applications"],
        "secret_fields": ["argocd_token"],
        "tools": [
            {"name": "list_apps", "description": "List ArgoCD applications"},
            {"name": "get_app_status", "description": "Read sync and health status of one app"},
            {"name": "sync_app", "description": "Trigger an ArgoCD sync"},
            {"name": "get_rollout_status", "description": "Inspect rollout and operation state"},
            {"name": "rollback_app", "description": "Rollback an ArgoCD application"},
            {"name": "list_events", "description": "List recent ArgoCD events for an app"},
        ],
        "example": {
            "argocd_url": "https://argocd.example.com",
            "argocd_token": "argocd-api-token",
            "argocd_allowed_applications": ["sample-api", "sample-worker"],
        },
    },
    "terraform": {
        "label": "Terraform / OpenTofu",
        "description": "Local terraform or opentofu execution against an allowed workspace root.",
        "fields": [
            "terraform_root",
            "terraform_binary",
            "terraform_use_opentofu",
            "terraform_workspace",
            "terraform_allowed_workspaces",
            "terraform_var_file",
            "terraform_plugin_cache_dir",
        ],
        "tools": [
            {"name": "plan", "description": "Run terraform or opentofu plan"},
            {"name": "apply", "description": "Run terraform or opentofu apply with approval"},
            {"name": "show_state", "description": "Show current state"},
            {"name": "list_resources", "description": "List resources from state"},
            {"name": "get_output", "description": "Read outputs"},
            {"name": "workspace_select", "description": "Select or create a workspace"},
        ],
        "example": {
            "terraform_root": "infra/terraform",
            "terraform_binary": "terraform",
            "terraform_use_opentofu": False,
            "terraform_workspace": "prod",
            "terraform_allowed_workspaces": ["dev", "prod"],
            "terraform_var_file": "env/prod.tfvars",
            "terraform_plugin_cache_dir": ".terraform.d/plugin-cache",
        },
    },
    "ldap": {
        "label": "LDAP / Active Directory",
        "description": "Directory lookup plus local Octryx user provisioning from LDAP or Active Directory.",
        "fields": [
            "ldap_server_url",
            "ldap_bind_dn",
            "ldap_bind_password",
            "ldap_base_dn",
            "ldap_user_base_dn",
            "ldap_group_base_dn",
            "ldapsearch_binary",
            "ldap_mode",
            "ldap_uid_attribute",
            "ldap_email_attribute",
            "ldap_display_name_attribute",
            "ldap_group_name_attribute",
            "ldap_membership_attribute",
            "ldap_user_filter",
            "ldap_group_filter",
        ],
        "secret_fields": ["ldap_bind_password"],
        "tools": [
            {"name": "search_user", "description": "Search LDAP or Active Directory users"},
            {"name": "get_groups", "description": "List groups or group memberships"},
            {"name": "check_membership", "description": "Check if a user belongs to a group"},
            {"name": "sync_users", "description": "Sync directory users into the local user store"},
            {"name": "user_provisioning", "description": "Provision a local user from directory data"},
        ],
        "example": {
            "ldap_server_url": "ldap://ad.example.com:389",
            "ldap_bind_dn": "cn=svc-octryx,ou=Service Accounts,dc=example,dc=com",
            "ldap_bind_password": "ldap-bind-password",
            "ldap_base_dn": "dc=example,dc=com",
            "ldap_user_base_dn": "ou=Users,dc=example,dc=com",
            "ldap_group_base_dn": "ou=Groups,dc=example,dc=com",
            "ldapsearch_binary": "/opt/homebrew/bin/ldapsearch",
            "ldap_mode": "active_directory",
            "ldap_uid_attribute": "sAMAccountName",
            "ldap_email_attribute": "mail",
            "ldap_display_name_attribute": "displayName",
            "ldap_group_name_attribute": "cn",
            "ldap_membership_attribute": "member",
            "ldap_user_filter": "(objectClass=user)",
            "ldap_group_filter": "(objectClass=group)",
        },
    },
    "outlook_calendar": {
        "label": "Outlook / Exchange Calendar",
        "description": "Microsoft Graph-backed Outlook or Exchange calendar access for free/busy, meetings and absence workflows.",
        "fields": [
            "outlook_tenant_id",
            "outlook_client_id",
            "outlook_client_secret",
            "outlook_access_token",
            "outlook_graph_url",
            "outlook_default_mailbox",
            "outlook_allowed_mailboxes",
            "outlook_absence_mailboxes",
            "outlook_time_zone",
        ],
        "secret_fields": ["outlook_client_secret", "outlook_access_token"],
        "tools": [
            {"name": "get_free_busy", "description": "Read free/busy information for one or more mailboxes"},
            {"name": "list_meetings", "description": "List calendar meetings in a time window"},
            {"name": "create_meeting", "description": "Create a new calendar meeting"},
            {"name": "find_next_slot", "description": "Find the next free slot across mailboxes"},
            {"name": "check_absence", "description": "Check out-of-office or absence entries"},
            {"name": "send_meeting_invite", "description": "Create and send a meeting invite"},
        ],
        "example": {
            "outlook_tenant_id": "tenant-id",
            "outlook_client_id": "client-id",
            "outlook_client_secret": "client-secret",
            "outlook_graph_url": "https://graph.microsoft.com/v1.0",
            "outlook_default_mailbox": "alice@example.com",
            "outlook_allowed_mailboxes": ["alice@example.com", "team-calendar@example.com"],
            "outlook_absence_mailboxes": ["alice@example.com"],
            "outlook_time_zone": "UTC",
        },
    },
}
