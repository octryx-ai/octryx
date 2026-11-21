"""How each connector is recognised as active for a project.

``tools/visibility.py::connector_activation_decision`` reads these tables. A
connector is active when the project activates it explicitly (``enabled_connectors``,
``connectors.<name>.enabled``, ``<name>_enabled`` ... under any alias below), or,
without an explicit decision, when one of its configuration keys carries a value in
the resolved project config, or when a usable named connection of the
Workspace or a global one serves it (``named_connections.resolver.serving_connection``;
the routes exist only while the Workspace's own entry of the connector is active, and
the tool router still limits each connection to its bound keys). The resolved project
config is ``Project.config`` merged with the project's active tool configs (``services/tool_config``), so a connector
granted to a project through the admin connector access carries its preset fields.

The configuration keys of a connector mirror the fields of its tool-config preset
(``services/tool_config/presets_*.py``), so a project that has the connector
configured keeps its tools; ``tests/test_connector_tool_ownership.py`` pins that
parity. A key only has to be present; its value is never read or reported here.

A composite connector owns tools that serve several providers (for example CI tools
that run against GitHub, GitLab or Azure DevOps). It is active when activated
explicitly, when one of its own keys is set, or when any member connector is active.
An explicit deactivation of the composite always wins.
"""

from __future__ import annotations

CONNECTOR_ALIASES: dict[str, set[str]] = {
    "aws": {"aws", "amazon-web-services", "amazon_web_services"},
    "azure": {"azure", "microsoft-azure", "microsoft_azure"},
    "azure_devops": {"azure_devops", "azure-devops"},
    "bitbucket": {"bitbucket", "bitbucket-server", "bitbucket_server"},
    "confluence": {"confluence", "atlassian-confluence", "atlassian_confluence"},
    "docker_registry": {"docker_registry", "docker-registry", "harbor"},
    "gcp": {"gcp", "google-cloud", "google_cloud"},
    "github": {"github", "github-enterprise", "github_enterprise"},
    "gitlab": {"gitlab", "gitlab-enterprise", "gitlab_enterprise"},
    "incident_management": {"incident_management", "incident-management", "incident", "pagerduty", "opsgenie"},
    "jira": {"jira", "atlassian-jira", "atlassian_jira"},
    "newrelic": {"newrelic", "new_relic", "new-relic"},
    "outlook": {"outlook", "outlook_calendar", "outlook-calendar"},
    "servicenow": {"servicenow", "service-now", "service_now"},
    "statuspage": {"statuspage", "statuspage_io", "statuspage-io"},
}

CONNECTOR_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "ansible": (
        "ansible_playbook_root",
        "ansible_inventory_path",
        "ansible_playbook_binary",
        "ansible_inventory_binary",
        "ansible_binary",
        "ansible_allowed_playbooks",
        "ansible_allowed_hosts",
    ),
    "argocd": ("argocd_url", "argocd_token", "argocd_allowed_applications"),
    "aws": (
        "aws_region",
        "aws_default_region",
        "aws_account_id",
        "aws_profile",
        "aws_assume_role_arn",
        "aws_role_arn",
        "aws_enabled",
        "aws_allowed_services",
        "eks_cluster_name",
    ),
    "azure": (
        "azure_enabled",
        "azure_tenant_id",
        "azure_subscription_id",
        "azure_subscription_ids",
        "azure_client_id",
        "azure_access_token",
        "azure_resource_group",
    ),
    "azure_devops": ("azure_devops_url", "azure_devops_pat", "azure_devops_project", "azure_devops_allowed_projects"),
    "bitbucket": (
        "bitbucket_url",
        "bitbucket_allowed_repos",
        "bitbucket_project_key",
        "bitbucket_workspace",
    ),
    "confluence": (
        "confluence_url",
        "confluence_space_key",
        "confluence_allowed_spaces",
        "confluence_allowed_pages",
        "confluence_root_page_id",
    ),
    "datadog": ("datadog_url", "datadog_api_key", "datadog_app_key", "datadog_web_url"),
    "docker_registry": (
        "docker_registry_provider",
        "docker_registry_url",
        "docker_registry_username",
        "docker_registry_password",
        "docker_registry_token",
        "docker_registry_allowed_repositories",
        "harbor_project",
    ),
    "elasticsearch": (
        "elasticsearch_url",
        "elasticsearch_username",
        "elasticsearch_password",
        "elasticsearch_api_key",
        "elasticsearch_allowed_indices",
    ),
    "gcp": ("gcp_enabled", "gcp_project_id", "gcp_credentials_ref", "gcp_access_token", "gcp_allowed_services"),
    "github": (
        "github_url",
        "github_owner",
        "github_owner_type",
        "github_allowed_repositories",
        "github_repository",
    ),
    "gitlab": ("gitlab_url", "gitlab_project", "gitlab_project_path", "gitlab_allowed_projects"),
    "grafana": ("grafana_url", "grafana_token"),
    "helm": (
        "helm_binary",
        "helm_workspace_root",
        "helm_kubeconfig",
        "helm_namespace",
        "helm_allowed_namespaces",
        "helm_allowed_releases",
        "helm_allowed_charts",
        "helm_chart",
    ),
    "incident_management": (
        "incident_management_enabled",
        "incident_provider",
        "statuspage_page_id",
        "pagerduty_service_id",
        "pagerduty_service_ids",
        "opsgenie_team_id",
        "opsgenie_team_ids",
    ),
    "jira": ("jira_url", "jira_project_key", "jira_project_keys", "jira_projects", "jira_allowed_projects"),
    "ldap": (
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
    ),
    "linear": ("linear_url", "linear_api_key", "linear_team_id", "linear_allowed_teams"),
    "newrelic": ("newrelic_url", "newrelic_api_key", "newrelic_account_id", "newrelic_web_url"),
    "notion": ("notion_token", "notion_workspace", "notion_allowed_pages", "notion_allowed_databases"),
    "outlook": (
        "outlook_tenant_id",
        "outlook_client_id",
        "outlook_client_secret",
        "outlook_access_token",
        "outlook_graph_url",
        "outlook_default_mailbox",
        "outlook_allowed_mailboxes",
        "outlook_absence_mailboxes",
        "outlook_time_zone",
    ),
    "servicenow": ("servicenow_url", "servicenow_instance_url", "servicenow_enabled"),
    "sharepoint": (
        "sharepoint_url",
        "sharepoint_tenant_id",
        "sharepoint_client_id",
        "sharepoint_client_secret",
        "sharepoint_access_token",
        "sharepoint_site_paths",
    ),
    "snyk": ("snyk_url", "snyk_token", "snyk_org_id", "snyk_allowed_projects", "snyk_web_url"),
    "sonarqube": ("sonarqube_url", "sonarqube_token", "sonarqube_allowed_projects"),
    "splunk": ("splunk_url", "splunk_token", "splunk_username", "splunk_password", "splunk_allowed_indexes"),
    "statuspage": (
        "statuspage_url",
        "statuspage_api_key",
        "statuspage_page_id",
        "statuspage_allowed_page_ids",
        "statuspage_allowed_component_ids",
        "statuspage_web_url",
    ),
    "terraform": (
        "terraform_root",
        "terraform_binary",
        "terraform_use_opentofu",
        "terraform_workspace",
        "terraform_allowed_workspaces",
        "terraform_var_file",
        "terraform_plugin_cache_dir",
    ),
    "vault": (
        "vault_url",
        "vault_token",
        "vault_namespace",
        "vault_kv_mount",
        "vault_allowed_paths",
        "vault_audit_path",
    ),
    # Composite connectors: their own keys are exactly the signals the tools use to
    # pick a provider (``connectors/ci_logs.py::_ci_provider``,
    # ``connectors/issues.py::_issues_provider``).
    "ci_pipelines": (
        "azure_devops_url",
        "azure_devops_pat",
        "azure_devops_project",
        "gitlab_url",
        "gitlab_token",
        "gitlab_token_secret_ref",
        "gitlab_group",
        "github_url",
        "github_token",
        "github_token_secret_ref",
        "github_owner",
    ),
    "sonarqube_linear_issues": ("issues_provider", "linear_api_key", "linear_url", "sonarqube_url", "sonarqube_token"),
}

COMPOSITE_CONNECTOR_MEMBERS: dict[str, tuple[str, ...]] = {
    "ci_pipelines": ("github", "gitlab", "azure_devops"),
    "newrelic_splunk_alerts": ("newrelic", "splunk"),
    "sonarqube_linear_issues": ("sonarqube", "linear"),
}

__all__ = ["COMPOSITE_CONNECTOR_MEMBERS", "CONNECTOR_ALIASES", "CONNECTOR_CONFIG_KEYS"]
