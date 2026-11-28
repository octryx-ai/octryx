"""Save-time validation and failure hints of the Atlassian connector authentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .atlassian_modes import (
    _FIELD_LABELS,
    _LABELS,
    _MODE_FIELDS,
    AUTH_FAILURE_HINTS,
    AUTH_MODES,
    BITBUCKET,
    BITBUCKET_CLOUD_MODES,
    CODE_AUTH_INVALID,
    CODE_CLOUD_URL_WITHOUT_WIKI,
    CODE_JIRA_CLOUD_URL_WITH_PATH,
    CONFLUENCE,
    JIRA,
    MODE_BASIC,
    MODE_BEARER_PAT,
    MODE_CLOUD_API_TOKEN,
    MODE_FIELDS,
    MODE_OIDC_CLIENT_CREDENTIALS,
    AtlassianAuthConfigError,
    _text,
    declared_mode,
    is_bitbucket_cloud,
)
from .oidc_client_credentials import CODE_TOKEN_URL_INVALID, MESSAGES, config_problems, product_fields


def _present(config: Mapping[str, Any], key: str) -> bool:
    return bool(_text(config, key) or _text(config, f"{key}_secret_ref"))


def mode_credential_fields(connector: str, mode: object) -> tuple[str, ...] | None:
    fields = _MODE_FIELDS.get(connector, {}).get(mode) if isinstance(mode, str) else None
    return None if fields is None else tuple(key for key in fields if key)


def missing_fields(connector: str, mode: str, config: Mapping[str, Any]) -> list[str]:
    principal_key, secret_key = _MODE_FIELDS[connector][mode]
    keys = [key for key in (principal_key, secret_key) if key]
    return [key for key in keys if not _present(config, key)]


def validate_auth_config(connector: str, config: Mapping[str, Any]) -> None:
    if connector == "servicenow":  # the same writers validate ServiceNow's explicit mode
        from .servicenow import validate_servicenow_auth_config

        validate_servicenow_auth_config(config)
        return
    if connector not in MODE_FIELDS:
        return
    if connector == CONFLUENCE and isinstance(config.get("confluence_url"), str):
        # Refused at save for both scopes, never rewritten (same rule as the connection test).
        problem = confluence_cloud_url_problem(config["confluence_url"])
        if problem:
            raise AtlassianAuthConfigError(problem, code=CODE_CLOUD_URL_WITHOUT_WIKI)
    if connector == JIRA and isinstance(config.get("jira_url"), str):
        problem = jira_cloud_url_problem(config["jira_url"])
        if problem:
            raise AtlassianAuthConfigError(problem, code=CODE_JIRA_CLOUD_URL_WITH_PATH)
    mode = declared_mode(connector, config)
    if mode is None:
        _refuse_credentials_without_mode(connector, config)
        return
    if not isinstance(mode, str) or mode not in AUTH_MODES:
        raise AtlassianAuthConfigError(
            f"{MODE_FIELDS[connector]} must be one of: {', '.join(AUTH_MODES)}."
        )
    if connector == BITBUCKET and is_bitbucket_cloud(config) and mode not in BITBUCKET_CLOUD_MODES:
        raise AtlassianAuthConfigError(
            "Bitbucket Cloud signs in with the Atlassian account email and an API token: bitbucket_auth_mode "
            f"must be {MODE_CLOUD_API_TOKEN} or empty (OpenID Connect, personal access tokens and passwords are "
            "for Bitbucket Server/Data Center)."
        )
    if mode == MODE_OIDC_CLIENT_CREDENTIALS:
        problems = config_problems(config, product_fields(connector), present=lambda key: _present(config, key))
        if problems:
            text = "; ".join(problem.rstrip(".") for problem in problems)
            code = CODE_TOKEN_URL_INVALID if MESSAGES[CODE_TOKEN_URL_INVALID].rstrip(".") in text else CODE_AUTH_INVALID
            raise AtlassianAuthConfigError(f"{_LABELS[connector]} {_mode_label(mode)}: {text}.", code=code)
        return
    missing = missing_fields(connector, mode, config)
    if missing:
        names = ", ".join(_FIELD_LABELS[key] for key in missing)
        raise AtlassianAuthConfigError(f"{_LABELS[connector]} {_mode_label(mode)} needs: {names}.")


def _refuse_credentials_without_mode(connector: str, config: Mapping[str, Any]) -> None:
    # Bitbucket Cloud has one sign-in and needs no mode.
    if connector == BITBUCKET and is_bitbucket_cloud(config):
        return
    fields = {key for pair in _MODE_FIELDS[connector].values() for key in pair if key}
    if any(_present(config, key) for key in sorted(fields)):
        raise AtlassianAuthConfigError(
            f"{_LABELS[connector]} credentials need {MODE_FIELDS[connector]}: one of {', '.join(AUTH_MODES)}."
        )


def _mode_label(mode: str) -> str:
    return {
        MODE_CLOUD_API_TOKEN: "Atlassian Cloud (email and API token)",
        MODE_BASIC: "username and password",
        MODE_BEARER_PAT: "personal access token",
        MODE_OIDC_CLIENT_CREDENTIALS: "OpenID Connect client credentials",
    }[mode]


def auth_failure_hint(connector: str, config: Mapping[str, Any]) -> str:
    mode = declared_mode(connector, config)
    return AUTH_FAILURE_HINTS.get(mode if isinstance(mode, str) else None, AUTH_FAILURE_HINTS[None])


def jira_cloud_url_problem(url: str) -> str | None:
    # The browser address ``.../jira`` is refused, never rewritten: it can test ok while every search answers 404.
    from urllib.parse import urlsplit

    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower()
    if host.endswith(".atlassian.net") and parts.path.strip("/"):
        return "Atlassian Cloud Jira URLs are the site root, for example https://your-site.atlassian.net (no /jira)."
    return None


def confluence_cloud_url_problem(url: str) -> str | None:
    # A bare ``*.atlassian.net`` URL is refused, never rewritten.
    from urllib.parse import urlsplit

    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower()
    if host.endswith(".atlassian.net") and not parts.path.rstrip("/").endswith("/wiki"):
        return "Atlassian Cloud Confluence URLs end with /wiki, for example https://your-site.atlassian.net/wiki."
    return None
