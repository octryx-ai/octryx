"""Bitbucket, GitHub and GitLab: named connections per instance or technical user, bound to repositories.

- **Bitbucket** binds repositories (``PROJECT/repo``, its allowlist holds repositories only); a call names
  ``project_key`` and ``repo_slug``.
- **GitHub** binds an owner (``acme``: every repository of it) or a repository (``acme/payments``); a call
  names ``repository`` (``owner/repo``) and/or ``owner``. The most specific binding wins.
- **GitLab** binds a group (``risk``, nested groups included) or a project path (``risk/payments``); a call
  names ``project`` (a path; a numeric id names no key).

Each connection is a URL and a token (Bitbucket: see below). A Bitbucket connection
names where Bitbucket runs (``bitbucket_deployment``): ``datacenter`` (Server/Data Center, the default of a
connection that names none) or ``cloud`` (bitbucket.org: the Atlassian account email as username and a scoped
Atlassian API token; ``tools/bitbucket_impl/_bitbucket_cloud.py``). A Server/Data Center connection signs in like
Jira (``bitbucket_auth_mode``, ``services/atlassian_auth.py``): ``basic`` (username and password),
``bearer_pat`` (an HTTP access token as Bearer) or ``oidc_client_credentials`` (an OpenID Connect client
credentials grant at the admin-entered token endpoint; its access token as Bearer); without a mode it has no
credential. A Cloud connection takes no mode or ``cloud_api_token``. A named connection without its credential
is refused at call time instead of calling the API anonymously. A connection bound to whole owners or groups reads
with its token only; bound repositories narrow its allowlist to them. The shared CI tools (job and pipeline logs,
artifacts, test results, ...) are GitHub's or GitLab's by their ``provider``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.services.atlassian_auth_modes import BITBUCKET as BITBUCKET_CONNECTOR
from app.services.atlassian_auth_modes import BITBUCKET_AUTH_MODES, AtlassianAuthConfigError, declared_mode
from app.services.atlassian_auth_validation import validate_auth_config

from ...atlassian_auth import resolve_credential
from ...oidc_client_credentials import CLIENT_AUTH_METHODS
from ..descriptor import (
    CASE_LOWER,
    UNSCOPED_SINGLE,
    Allowlist,
    Binding,
    ConnectorDescriptor,
    Field,
    UnitIncompleteError,
    present,
    require_fields,
)

_SEGMENT = r"[A-Za-z0-9_.~-]+"
SHARED_CI_TOOLS = frozenset({
    "get_job_logs", "get_pipeline_logs", "trigger_workflow", "retry_job", "cancel_pipeline", "list_artifacts",
    "get_artifact", "get_test_results",
})


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unavailable(message: str) -> UnitIncompleteError:
    return UnitIncompleteError("named_connection_credential_unavailable", message)


# --- Bitbucket -----------------------------------------------------------------------------------------------


BITBUCKET_DEPLOYMENT = "bitbucket_deployment"
# The sign-in form with auth modes like Jira's, whose fields depend on where Bitbucket runs (frontend authFields.ts).
FORM_BITBUCKET = "bitbucket_auth"
DEPLOYMENT_DATACENTER, DEPLOYMENT_CLOUD = "datacenter", "cloud"
CLOUD_HOSTS = frozenset({"bitbucket.org", "api.bitbucket.org"})


def _bitbucket_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    project, repo = _text(params.get("project_key")), _text(params.get("repo_slug"))
    return (f"{project}/{repo}",) if project and repo else ()


def _bitbucket_rule_key(entry: Any) -> str:
    if isinstance(entry, dict):
        project = str(entry.get("project_key") or entry.get("project") or "").strip()
        repo = str(entry.get("repo_slug") or entry.get("slug") or "").strip()
        return f"{project}/{repo}" if project and repo else ""
    return str(entry or "").strip()


def _bitbucket_entry(key: str) -> dict[str, Any]:
    project, repo = key.split("/", 1)
    return {"project_key": project.upper(), "repo_slug": repo, "enabled": True}


def _bitbucket_complete(config: dict) -> None:
    require_fields(config, "bitbucket_url")
    deployment = _text(config.get(BITBUCKET_DEPLOYMENT)) or DEPLOYMENT_DATACENTER
    if deployment not in (DEPLOYMENT_DATACENTER, DEPLOYMENT_CLOUD):
        raise UnitIncompleteError("connection_invalid", "bitbucket_deployment is cloud or datacenter.")
    try:  # the mode: closed set, its own principal and secret, Cloud only with cloud_api_token
        validate_auth_config(BITBUCKET_CONNECTOR, config)
    except AtlassianAuthConfigError as exc:
        raise UnitIncompleteError(exc.code, str(exc)) from None
    if deployment == DEPLOYMENT_CLOUD:
        if (urlsplit(_text(config.get("bitbucket_url"))).hostname or "").lower() not in CLOUD_HOSTS:
            raise UnitIncompleteError("connection_invalid", "A Bitbucket Cloud connection's URL is https://bitbucket.org.")
        if not (present(config, "bitbucket_username") and present(config, "bitbucket_token")):
            raise UnitIncompleteError(
                "connection_invalid",
                "A Bitbucket Cloud connection needs the Atlassian account email (bitbucket_username) and an "
                "Atlassian API token with Bitbucket scopes (bitbucket_token).",
            )
        return
    if declared_mode(BITBUCKET_CONNECTOR, config) is None:
        raise UnitIncompleteError(
            "connection_invalid",
            "An own connection needs bitbucket_auth_mode and the credential of that sign-in.",
        )


def _resolved(config: dict, name: str) -> bool:
    return bool(_text(config.get(name)))


def _bitbucket_guard(config: dict) -> None:
    if _text(config.get(BITBUCKET_DEPLOYMENT)) == DEPLOYMENT_CLOUD:
        if not _resolved(config, "bitbucket_url"):
            raise _unavailable("its URL or credential is not available (no anonymous call).")
        if not (_resolved(config, "bitbucket_username") and _resolved(config, "bitbucket_token")):
            raise _unavailable("a Bitbucket Cloud call needs the account email and its API token.")
        return
    if not (_resolved(config, "bitbucket_url") and resolve_credential(BITBUCKET_CONNECTOR, config) is not None):
        raise _unavailable("its URL or credential is not available (no anonymous call).")


BITBUCKET = ConnectorDescriptor(
    connector="bitbucket",
    label="Bitbucket",
    binding=Binding("repository", "Repositories", rf"{_SEGMENT}/{_SEGMENT}", CASE_LOWER,
                    "PROJECT/repo-1, PROJECT/repo-2"),
    fields=(
        # The options read "Server / Data Center" and "Bitbucket Cloud" in the form (frontend authFields.ts).
        Field(BITBUCKET_DEPLOYMENT, "Where Bitbucket runs", kind="select",
              options=(DEPLOYMENT_DATACENTER, DEPLOYMENT_CLOUD)),
        Field("bitbucket_url", "Bitbucket URL", kind="url", required=True,
              placeholder="https://bitbucket.example.com"),
        Field("bitbucket_auth_mode", "Authentication", kind="select", options=BITBUCKET_AUTH_MODES),
        Field("bitbucket_username", "Username"),
        Field("bitbucket_password", "Password", kind="secret"),
        Field("bitbucket_token", "HTTP access token", kind="secret"),
        Field("bitbucket_oidc_token_url", "OpenID Connect token endpoint URL", kind="url",
              placeholder="https://idp.example.com/oauth2/token"),
        Field("bitbucket_oidc_client_id", "Client id"),
        Field("bitbucket_oidc_client_secret", "Client secret", kind="secret"),
        Field("bitbucket_oidc_scope", "Scope (optional)"),
        Field("bitbucket_oidc_audience", "Audience (optional)"),
        Field("bitbucket_oidc_client_auth", "Client authentication (optional)", kind="select",
              options=CLIENT_AUTH_METHODS),
    ),
    usable_field="bitbucket_url",
    request_keys=_bitbucket_keys,
    allowlist=Allowlist("bitbucket_allowed_repos", serves_unlisted=False, rule_key=_bitbucket_rule_key,
                        entry=_bitbucket_entry),
    unscoped=UNSCOPED_SINGLE,
    tool_names=frozenset({"search_bitbucket_users", "update_bitbucket_pull_request", "get_bitbucket_build_statuses",
                          "add_bitbucket_pull_request_comment", "list_bitbucket_pull_request_heads",
                          "post_bitbucket_pull_request_review"}),
    complete=_bitbucket_complete,
    runtime_guard=_bitbucket_guard,
    form=FORM_BITBUCKET,
)


# --- GitHub and GitLab ---------------------------------------------------------------------------------------


def _repositories_only(rules: list[Any], keys: frozenset[str]) -> list[Any]:
    """Bound repositories narrow the list; a bound owner or group leaves it open (the token decides)."""
    return [] if any("/" not in key for key in keys) else rules


def _github_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    repository = _text(params.get("repository") or params.get("repo"))
    owner = _text(params.get("owner"))
    if "/" in repository:
        return (repository,)
    if owner and repository:
        return (f"{owner}/{repository}",)
    return (owner,) if owner else ()


def _token_guard(url_field: str | None, token_field: str):
    def guard(config: dict) -> None:
        if (url_field and not _resolved(config, url_field)) or not _resolved(config, token_field):
            raise _unavailable("its URL or token is not available (no anonymous call).")

    return guard


def _github_complete(config: dict) -> None:
    require_fields(config, "github_token")


GITHUB = ConnectorDescriptor(
    connector="github",
    label="GitHub",
    binding=Binding("repository or owner", "Repositories or owners", rf"{_SEGMENT}(/{_SEGMENT})?", CASE_LOWER,
                    "owner, owner/repo", hierarchical=True),
    fields=(
        Field("github_url", "GitHub API URL (empty: github.com)", kind="url",
              placeholder="https://github.example.com/api/v3"),
        Field("github_owner", "Default owner"),
        Field("github_owner_type", "Owner type", kind="select", options=("org", "user")),
        Field("github_token", "Token", kind="secret", required=True),
    ),
    usable_field="github_url",
    default_usable_fields=("github_token", "github_token_secret_ref", "github_owner"),
    request_keys=_github_keys,
    allowlist=Allowlist("github_allowed_repositories", narrow=_repositories_only),
    unscoped=UNSCOPED_SINGLE,
    named_drops=("github_clone_base_url", "github_web_url"),
    tool_names=frozenset({
        "read_github_file", "list_github_branches", "create_github_branch", "prepare_github_repository",
        "commit_and_push_github_repository_branch", "get_github_pull_request", "create_github_pull_request",
        "update_github_pull_request", "list_github_issues", "get_github_issue", "create_github_issue",
        "update_github_issue", "list_github_pull_request_heads", "post_github_pull_request_review",
        "get_github_commit_checks",
    }),
    shared_tools=SHARED_CI_TOOLS,
    complete=_github_complete,
    runtime_guard=_token_guard(None, "github_token"),
)


def _gitlab_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    project = _text(params.get("project") or params.get("project_id"))
    return (project.strip("/"),) if project and not project.isdigit() else ()


def _gitlab_complete(config: dict) -> None:
    require_fields(config, "gitlab_url", "gitlab_token")


GITLAB = ConnectorDescriptor(
    connector="gitlab",
    label="GitLab",
    binding=Binding("group or project", "Groups or projects", rf"{_SEGMENT}(/{_SEGMENT})*", CASE_LOWER,
                    "group, group/project", hierarchical=True),
    fields=(
        Field("gitlab_url", "GitLab URL", kind="url", required=True, placeholder="https://gitlab.example.com"),
        Field("gitlab_group", "Default group"),
        Field("gitlab_token", "Token", kind="secret", required=True),
    ),
    usable_field="gitlab_url",
    request_keys=_gitlab_keys,
    allowlist=Allowlist("gitlab_allowed_projects", narrow=_repositories_only),
    unscoped=UNSCOPED_SINGLE,
    tool_names=frozenset({
        "read_gitlab_file", "list_gitlab_branches", "create_gitlab_branch", "prepare_gitlab_repository",
        "commit_and_push_gitlab_repository_branch", "get_gitlab_merge_request", "create_gitlab_merge_request",
        "update_gitlab_merge_request", "list_gitlab_merge_request_heads", "post_gitlab_merge_request_review",
        "get_gitlab_commit_checks",
    }),
    shared_tools=SHARED_CI_TOOLS,
    complete=_gitlab_complete,
    runtime_guard=_token_guard("gitlab_url", "gitlab_token"),
    testable=False,
)

__all__ = ["BITBUCKET", "GITHUB", "GITLAB", "SHARED_CI_TOOLS"]
