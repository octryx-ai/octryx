"""Validation helpers for built-in tool configs."""

from __future__ import annotations

from typing import Any

from app.services.confluence_pages.rules import validate_page_rules
from app.services.connector_auth.atlassian_validation import validate_auth_config
from app.services.servicenow_record_limit import (
    GROUPS_FIELD,
    MODE_FIELD,
    SERVICES_FIELD,
    normalize_entries,
    normalize_mode,
)
from app.services.tool_config.presets import TOOL_CONFIG_PRESETS
from app.services.tool_config.web_url import WEB_URL_FIELD_SUFFIX, validate_web_url_field


def normalize_field_type(example_value: Any) -> str:
    if isinstance(example_value, bool):
        return "bool"
    if isinstance(example_value, int) and not isinstance(example_value, bool):
        return "int"
    if isinstance(example_value, dict):
        return "dict"
    if isinstance(example_value, list):
        return "list"
    return "str"


def validate_string_list(name: str, value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")


def validate_object_list(name: str, value: Any, *, required_keys: tuple[str, ...]) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{name} must contain objects")
        for key in required_keys:
            if not str(item.get(key) or "").strip():
                raise ValueError(f"{name} entries must include {key}")


def validate_tool_config(tool_name: str, config: dict[str, Any]) -> dict[str, Any]:
    preset = TOOL_CONFIG_PRESETS.get(tool_name)
    if not preset:
        raise ValueError(f"Unknown tool config preset: {tool_name}")
    if not isinstance(config, dict):
        raise ValueError("tool config must be an object")

    allowed_fields = set(preset.get("fields") or [])
    allowed_fields.update(f"{field}_secret_ref" for field in (preset.get("secret_fields") or []))
    unknown_fields = sorted(key for key in config.keys() if key not in allowed_fields)
    if unknown_fields:
        raise ValueError(f"Unknown config fields for {tool_name}: {', '.join(unknown_fields)}")

    example = preset.get("example") or {}
    for field_name, value in config.items():
        if value is None:
            continue
        if field_name.endswith("_secret_ref"):
            if not isinstance(value, str):
                raise ValueError(f"{field_name} must be a string")
            continue
        expected = normalize_field_type(example.get(field_name))
        if expected == "bool" and not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        if expected == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be an integer")
            if field_name.endswith("_port") and not (1 <= value <= 65535):
                raise ValueError(f"{field_name} must be between 1 and 65535")
        if expected == "str" and not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        if field_name == MODE_FIELD:
            normalize_mode(value)
        if field_name.endswith(WEB_URL_FIELD_SUFFIX):
            validate_web_url_field(field_name, value)
        if expected == "dict" and not isinstance(value, dict):
            raise ValueError(f"{field_name} must be an object")
        if expected != "list":
            continue
        if field_name in {
            "jira_allowed_projects",
            "servicenow_allowed_tables",
            "postgres_allowed_schemas",
            "notion_allowed_pages",
            "notion_allowed_databases",
            "sharepoint_site_paths",
            "elasticsearch_allowed_indices",
            "aws_allowed_services",
            "azure_subscription_ids",
            "gcp_allowed_services",
            "gitlab_allowed_projects",
            "github_allowed_repositories",
            "argocd_allowed_applications",
            "terraform_allowed_workspaces",
            "vault_allowed_paths",
            "sonarqube_allowed_projects",
            "ansible_allowed_playbooks",
            "ansible_allowed_hosts",
            "outlook_allowed_mailboxes",
            "outlook_absence_mailboxes",
            "pagerduty_service_ids",
            "pagerduty_schedule_ids",
            "pagerduty_escalation_policy_ids",
            "opsgenie_schedule_ids",
            "opsgenie_team_ids",
            "opsgenie_escalation_ids",
        }:
            validate_string_list(field_name, value)
        elif field_name in (GROUPS_FIELD, SERVICES_FIELD):
            # names or sys_ids; refuses separators and scripts (an only-narrowing limit)
            normalize_entries(value, field=field_name)
        elif field_name in {"bitbucket_allowed_repos"}:
            validate_object_list(field_name, value, required_keys=("project_key", "repo_slug"))
        elif field_name in {"confluence_allowed_spaces"}:
            validate_object_list(field_name, value, required_keys=("space_key",))
        elif field_name in {"confluence_allowed_pages"}:
            validate_page_rules(value)  # pages, subtrees with excludes, whole spaces
        elif field_name in {"jenkins_allowed_jobs"}:
            validate_object_list(field_name, value, required_keys=("job_name",))
        elif not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list")

    # A closed auth mode with its own principal and secret; credentials without a mode are refused.
    validate_auth_config(tool_name, config)
    return config
