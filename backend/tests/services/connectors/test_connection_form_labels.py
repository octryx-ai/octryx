"""Connection forms use plain labels in one order for every type."""

from __future__ import annotations

import pytest

from app.services.connections.catalog import list_connection_types
from app.services.connector_auth.oidc_client_credentials import CLIENT_AUTH_METHODS


def _fields(connection_type: str) -> list[dict]:
    entry = next(item for item in list_connection_types() if item["type"] == connection_type)
    return entry["access_fields"]


def _labels(connection_type: str) -> dict[str, str]:
    return {field["key"]: field["label"] for field in _fields(connection_type)}


def test_jira_reads_like_bitbucket() -> None:
    assert [field["label"] for field in _fields("jira")] == [
        "Jira URL", "Authentication", "Account email", "Username", "Password", "API token or personal access token",
        "OpenID Connect token endpoint URL", "Client id", "Client secret", "Scope (optional)", "Audience (optional)",
        "Client authentication (optional)",
    ]


def test_confluence_and_servicenow_start_with_their_url_and_authentication() -> None:
    assert [field["label"] for field in _fields("confluence")][:2] == ["Confluence URL", "Authentication"]
    servicenow = _labels("servicenow")
    assert [field["label"] for field in _fields("servicenow")][:2] == ["ServiceNow URL", "Authentication"]
    assert servicenow["servicenow_token"] == "Bearer token"
    assert servicenow["servicenow_token_url"] == "Token endpoint URL"


@pytest.mark.parametrize("connection_type", ["jira", "confluence", "servicenow", "bitbucket"])
def test_no_label_is_a_config_key(connection_type: str) -> None:
    for key, label in _labels(connection_type).items():
        words = key.split("_")
        assert connection_type.capitalize() + " " + " ".join(words[1:]) != label, label
        assert "_" not in label and " oidc " not in f" {label.lower()} " and "auth mode" not in label.lower(), label


@pytest.mark.parametrize("connection_type", ["jira", "confluence", "servicenow", "bitbucket"])
def test_client_authentication_is_a_choice_of_the_accepted_methods(connection_type: str) -> None:
    field = next(item for item in _fields(connection_type) if item["key"].endswith("_oidc_client_auth"))
    assert field["kind"] == "select"
    assert field["options"] == list(CLIENT_AUTH_METHODS)
    assert field["placeholder"] == ""


def test_where_bitbucket_runs_is_a_short_label() -> None:
    assert _labels("bitbucket")["bitbucket_deployment"] == "Where Bitbucket runs"


def test_types_with_an_allowlist_name_their_binding_and_its_empty_meaning() -> None:
    types = {entry["type"]: entry for entry in list_connection_types()}
    confluence, jira = types["confluence"]["binding"], types["jira"]["binding"]
    assert (confluence["plural"], confluence["allowlist_field"], confluence["serves_unlisted"]) == (
        "Spaces", "confluence_allowed_spaces", False)
    assert (jira["plural"], jira["allowlist_field"], jira["serves_unlisted"]) == ("Projects", "jira_allowed_projects", True)
    assert confluence["case"] == jira["case"] == "upper"
