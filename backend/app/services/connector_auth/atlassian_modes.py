"""Modes, field tables and config readers of the Atlassian connector authentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .oidc_client_credentials import CODE_CONNECTOR_UNAUTHORIZED, MESSAGES

CONFLUENCE = "confluence"
JIRA = "jira"
BITBUCKET = "bitbucket"

MODE_CLOUD_API_TOKEN = "cloud_api_token"
MODE_BASIC = "basic"
MODE_BEARER_PAT = "bearer_pat"
MODE_OIDC_CLIENT_CREDENTIALS = "oidc_client_credentials"
AUTH_MODES = (MODE_CLOUD_API_TOKEN, MODE_BASIC, MODE_BEARER_PAT, MODE_OIDC_CLIENT_CREDENTIALS)
# Bitbucket's sign-in kinds, Server/Data Center's first (a new connection starts with the first one).
BITBUCKET_AUTH_MODES = (MODE_BASIC, MODE_BEARER_PAT, MODE_OIDC_CLIENT_CREDENTIALS, MODE_CLOUD_API_TOKEN)
BITBUCKET_CLOUD_MODES = (MODE_CLOUD_API_TOKEN,)

SCHEME_BASIC = "basic"
SCHEME_BEARER = "bearer"
SCHEME_OIDC = "oidc"

MODE_FIELDS = {CONFLUENCE: "confluence_auth_mode", JIRA: "jira_auth_mode", BITBUCKET: "bitbucket_auth_mode"}

# (principal field or None, secret field) per connector and explicit mode.
_MODE_FIELDS: dict[str, dict[str, tuple[str | None, str]]] = {
    CONFLUENCE: {
        MODE_CLOUD_API_TOKEN: ("confluence_username", "confluence_token"),
        MODE_BASIC: ("confluence_username", "confluence_password"),
        MODE_BEARER_PAT: (None, "confluence_token"),
        MODE_OIDC_CLIENT_CREDENTIALS: ("confluence_oidc_client_id", "confluence_oidc_client_secret"),
    },
    JIRA: {
        MODE_CLOUD_API_TOKEN: ("jira_email", "jira_token"),
        MODE_BASIC: ("jira_username", "jira_password"),
        MODE_BEARER_PAT: (None, "jira_token"),
        MODE_OIDC_CLIENT_CREDENTIALS: ("jira_oidc_client_id", "jira_oidc_client_secret"),
    },
    BITBUCKET: {
        MODE_CLOUD_API_TOKEN: ("bitbucket_username", "bitbucket_token"),
        MODE_BASIC: ("bitbucket_username", "bitbucket_password"),
        MODE_BEARER_PAT: (None, "bitbucket_token"),
        MODE_OIDC_CLIENT_CREDENTIALS: ("bitbucket_oidc_client_id", "bitbucket_oidc_client_secret"),
    },
}
_LABELS = {CONFLUENCE: "Confluence", JIRA: "Jira", BITBUCKET: "Bitbucket"}
_FIELD_LABELS = {
    "confluence_username": "Confluence username (the account email for Atlassian Cloud)",
    "confluence_password": "Confluence password",
    "confluence_token": "Confluence API token or personal access token",
    "jira_email": "Jira account email",
    "jira_username": "Jira username",
    "jira_password": "Jira password",
    "jira_token": "Jira API token or personal access token",
    "bitbucket_username": "Bitbucket username",
    "bitbucket_password": "Bitbucket password",
    "bitbucket_token": "Bitbucket HTTP access token or API token",
    **{
        f"{product}_oidc_{key}": f"{label} OpenID Connect {name}"
        for product, label in (("confluence", "Confluence"), ("jira", "Jira"), ("bitbucket", "Bitbucket"))
        for key, name in (("token_url", "token endpoint URL"), ("client_id", "client id"),
                          ("client_secret", "client secret"))
    },
}

AUTH_FAILURE_HINTS = {
    MODE_CLOUD_API_TOKEN: (
        "Use your Atlassian account email and an API token from id.atlassian.com "
        "(Atlassian Cloud mode)."
    ),
    MODE_BASIC: "Check the username and password; the server may have basic authentication disabled.",
    MODE_BEARER_PAT: (
        "Check the personal access token. For an own Server/Data Center instance use "
        "Personal access token mode; for Atlassian Cloud use Atlassian Cloud mode."
    ),
    MODE_OIDC_CLIENT_CREDENTIALS: MESSAGES[CODE_CONNECTOR_UNAUTHORIZED],
    None: (
        "Check the credentials, or choose the authentication mode: Atlassian Cloud (email and API token), "
        "username and password, or personal access token."
    ),
}


CODE_AUTH_INVALID = "atlassian_auth_invalid"
CODE_JIRA_CLOUD_URL_WITH_PATH = "jira_cloud_url_with_path"
CODE_CLOUD_URL_WITHOUT_WIKI = "confluence_cloud_url_without_wiki"
BITBUCKET_DEPLOYMENT_FIELD = "bitbucket_deployment"


class AtlassianAuthConfigError(ValueError):
    # The message names fields, never values.

    def __init__(self, message: str, *, code: str = CODE_AUTH_INVALID) -> None:
        super().__init__(message)
        self.code = code


def is_bitbucket_cloud(config: Mapping[str, Any]) -> bool:
    return str(config.get(BITBUCKET_DEPLOYMENT_FIELD) or "").strip().lower() == "cloud"


def _text(config: Mapping[str, Any], key: str) -> str:
    value = config.get(key)
    return value.strip() if isinstance(value, str) else ""


def declared_mode(connector: str, config: Mapping[str, Any]) -> str | None:
    raw = config.get(MODE_FIELDS[connector])
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return raw if not isinstance(raw, str) else raw.strip()
