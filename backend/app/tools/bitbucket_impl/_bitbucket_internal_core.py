"""Core Bitbucket helper utilities (non-network)."""

import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from sqlalchemy import select

from app.services.atlassian_auth_modes import BITBUCKET, SCHEME_BASIC, declared_mode
from app.services.atlassian_auth_validation import mode_credential_fields
from app.tools.context import ToolContext

from ...models import Project
from ...services.atlassian_auth import AtlassianCredential, credential_auth, resolve_credential
from ...services.git_http_auth import bearer_header_env, without_credentials
from ...services.oidc_client_credentials import OidcTokenError
from ...services.oidc_token_cache import access_token
from ...services.source_control import redact_source_control_text
from ..connectors.credential_boundary import connector_secret_value
from ._bitbucket_cloud import GIT_USERNAME as CLOUD_GIT_USERNAME
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_credentials
from ._bitbucket_cloud import clone_url as cloud_clone_url
from ._bitbucket_repository_token import repository_git_token

MAX_CONTENT_CHARS = 12000
# Values the Git output redaction removes when they are stored in plain text on the connection.
_CREDENTIAL_FIELDS = ("bitbucket_username", "bitbucket_password", "bitbucket_token")
_CREDENTIAL_URL_RE = re.compile(r"(https?://)(?:[^/\s:@]+(?::[^/\s@]*)?@)", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(authorization|api[_-]?key|password|token|secret|credential)(\s*[:=]\s*)([^\s]+)",
    re.IGNORECASE,
)


def _truncate(text: str) -> str:
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + "\n...[truncated]"


def _bitbucket_base_url(context: ToolContext) -> str:
    return str(context.project_config.get("bitbucket_url") or "").strip().rstrip("/")


async def _bitbucket_auth_config(context: ToolContext) -> dict[str, Any]:
    """The connection's config with the secret of its ``bitbucket_auth_mode`` resolved inside the connector boundary.

    Without a mode nothing is resolved: :func:`resolve_credential` then finds no credential (needs configuration).
    """
    config = dict(context.project_config or {})
    mode = declared_mode(BITBUCKET, config)
    if mode is None:
        return config
    fields = mode_credential_fields(BITBUCKET, mode) or ()
    for name in (name for name in fields if name.endswith(("_password", "_token", "_secret"))):
        value = await connector_secret_value(context, connector_name="bitbucket", field_name=name)
        if value:
            config[name] = value
    return config


async def _bitbucket_credential(context: ToolContext) -> AtlassianCredential | None:
    """The resolved credential of a Server/Data Center connection (``None``: incomplete or unknown mode)."""
    return resolve_credential(BITBUCKET, await _bitbucket_auth_config(context))


async def _bitbucket_http_auth(context: ToolContext) -> httpx.Auth | tuple[str, str] | None:
    """The ``httpx`` auth of the connection: ``(username, secret)`` for Basic, else a Bearer access
    token or the OpenID Connect grant's Bearer (renewed and retried once on a 401)."""
    credential = await _bitbucket_credential(context)
    if credential is None:
        return None
    if credential.scheme == SCHEME_BASIC:
        return credential.principal, credential.secret
    return credential_auth(credential)


async def _bitbucket_credentials_async(context: ToolContext) -> tuple[str, str] | None:
    """``(username, secret)`` of a Basic sign-in (``basic``, ``cloud_api_token``); ``None`` otherwise."""
    credential = await _bitbucket_credential(context)
    if credential is None or credential.scheme != SCHEME_BASIC:
        return None
    return credential.principal, credential.secret


def _managed_repo_root(context: ToolContext) -> Path:
    workspace_root = Path(context.workspace_root or Path.cwd()).resolve()
    configured = str(context.project_config.get("managed_repo_root") or "var/repos/bitbucket").strip()
    root = Path(configured).expanduser()
    resolved = root.resolve() if root.is_absolute() else (workspace_root / root).resolve()
    if workspace_root not in resolved.parents and resolved != workspace_root:
        raise ValueError(f"managed repo root must stay inside workspace root: {workspace_root}")
    return resolved


def _managed_repo_path(context: ToolContext, project_key: str, repo_slug: str) -> Path:
    return _managed_repo_root(context) / project_key / repo_slug


def _bitbucket_clone_url(
    context: ToolContext,
    project_key: str,
    repo_slug: str,
    *,
    include_credentials: bool = False,
) -> str:
    base_url = _bitbucket_base_url(context)
    if not base_url:
        raise ValueError("No Bitbucket URL configured for this project")
    if include_credentials:
        raise ValueError("Credentialed Bitbucket clone URLs are not supported; use connector-owned Git authentication")
    if cloud_context(context):
        return cloud_clone_url(project_key, repo_slug)

    split = urlsplit(base_url)
    clone_path = f"{split.path.rstrip('/')}/scm/{project_key}/{repo_slug}.git"
    return without_credentials(urlunsplit((split.scheme, split.netloc, clone_path, "", "")))


def _redact_bitbucket_git_output(context: ToolContext, text: str) -> str:
    redacted = redact_source_control_text(str(text or ""), max_length=MAX_CONTENT_CHARS)
    redacted = _CREDENTIAL_URL_RE.sub(r"\1redacted@", redacted)
    config = context.project_config or {}
    values = [str(config.get(name) or "").strip() for name in _CREDENTIAL_FIELDS]
    credential = resolve_credential(BITBUCKET, config)
    if credential is not None:
        values += [credential.principal, credential.secret]
    for value in values:
        if value:
            redacted = redacted.replace(value, "[redacted]")
            redacted = redacted.replace(quote(value, safe=""), "[redacted]")
    redacted = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
    return redact_source_control_text(redacted, max_length=MAX_CONTENT_CHARS)


def _require_connection_host(context: ToolContext, remote) -> None:
    """The token goes only to the connection's own host (review fix 2): bitbucket.org for Bitbucket Cloud, the
    configured host and port for Server/Data Center. A working copy whose remote points elsewhere gets nothing."""
    if cloud_context(context):
        expected = ("https", "bitbucket.org", None)
    else:
        configured = urlsplit(_bitbucket_base_url(context))
        expected = (configured.scheme.lower(), (configured.hostname or "").lower(), configured.port)
    actual = (remote.scheme.lower(), (remote.hostname or "").lower(), remote.port)
    if not expected[1] or actual != expected:
        raise ValueError("The Git remote is not this Bitbucket connection's host; no credential is sent to it.")


def _write_bitbucket_git_askpass_script() -> Path:
    askpass_path = Path(tempfile.gettempdir()) / "octryx-bitbucket-askpass.sh"
    askpass_path.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*|*username*) printf '%s\\n' \"$OCTRYX_BITBUCKET_USERNAME\" ;;\n"
        "  *Password*|*password*) printf '%s\\n' \"$OCTRYX_BITBUCKET_SECRET\" ;;\n"
        "  *) printf '\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    askpass_path.chmod(0o700)
    return askpass_path


async def _bitbucket_git_auth_env_async(context: ToolContext, remote_url: str) -> dict[str, str] | None:
    """The environment of a Git command against the connection's host, carrying its credential.

    Basic sign-ins (``basic``, Bitbucket Cloud) answer Git's prompts through the askpass script from
    environment variables. A Bearer sign-in (``bearer_pat``, ``oidc_client_credentials``) sends
    ``Authorization: Bearer <token>`` as ``http.<origin>/.extraHeader`` through ``GIT_CONFIG_*`` environment
    variables (``services/git_http_auth.py``). The token is never in argv, the remote URL or a file. A Server/Data
    Center repository with its own Git token (``_bitbucket_repository_token.py``) gets that token as the Bearer.
    """
    split = urlsplit(str(remote_url or ""))
    if split.scheme.lower() not in {"http", "https"}:
        return None
    _require_connection_host(context, split)
    if cloud_context(context):
        try:  # Bitbucket Cloud: the fixed Git user of Atlassian API tokens, never the account email
            username, secret = CLOUD_GIT_USERNAME, (await cloud_credentials(context))[1]
        except CloudApiError as error:
            raise ValueError(error.message) from None
    else:
        # The repository's own Git token when the Workspace set one (Data Center: 500 on /scm/ for the OIDC token).
        repository_token = await repository_git_token(context, remote_url)
        if repository_token:
            return bearer_header_env(remote_url, repository_token)
        credential = await _bitbucket_credential(context)
        if credential is None:
            raise ValueError("Bitbucket credentials are required for clone/fetch/pull/push operations")
        if credential.scheme != SCHEME_BASIC:
            try:
                token = credential.secret if credential.oidc is None else await access_token(credential.oidc)
            except OidcTokenError as error:  # a closed code and a fixed message, never the IdP's answer
                raise ValueError(str(error)) from None
            return bearer_header_env(remote_url, token)
        username, secret = credential.principal, credential.secret
    askpass_path = _write_bitbucket_git_askpass_script()
    env = dict(os.environ)
    env.update(
        {
            "GIT_ASKPASS": str(askpass_path),
            "GIT_TERMINAL_PROMPT": "0",
            "OCTRYX_BITBUCKET_USERNAME": username,
            "OCTRYX_BITBUCKET_SECRET": secret,
        }
    )
    return env


async def _run_git(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_sec: int = 90,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)``; a transient failure of a git network step is tried again with a backoff
    (``connectors.git_errors.run_with_retry``)."""
    from ..connectors.git_errors import run_with_retry

    return await run_with_retry(_run_git_once, command, cwd=cwd, timeout_sec=timeout_sec, env=env)


async def _run_git_once(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_sec: int = 90,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    import asyncio

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "", f"git command timed out after {timeout_sec}s"
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


async def _detect_default_branch(context: ToolContext, project_key: str, repo_slug: str) -> str:
    from . import _bitbucket_internal_network

    if cloud_context(context):
        from ._bitbucket_cloud_ops import default_branch

        return await default_branch(context, project_key, repo_slug)  # never a guessed "master" on Cloud
    try:
        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches/default",
        )
        return str(payload.get("displayId") or "master").strip() or "master"
    except Exception:
        return "master"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "all"}


def _should_scan_all_branches(context: ToolContext, params: dict[str, Any]) -> bool:
    if "include_all_branches" in params:
        return _as_bool(params.get("include_all_branches"))
    configured = context.project_config.get("bitbucket_scan_all_branches")
    if configured is not None:
        return _as_bool(configured)
    # The tool parameter or the Workspace setting decides; the prompt's wording never widens the scan.
    return False


async def _list_repo_branch_names(
    context: ToolContext,
    *,
    project_key: str,
    repo_slug: str,
    include_all_branches: bool,
    requested_branches: list[str],
) -> list[str]:
    from . import _bitbucket_internal_network

    normalized_requested = []
    seen_requested: set[str] = set()
    for branch in requested_branches:
        value = str(branch or "").strip()
        if not value or value in seen_requested:
            continue
        seen_requested.add(value)
        normalized_requested.append(value)
    if normalized_requested:
        return normalized_requested

    default_branch = await _detect_default_branch(context, project_key, repo_slug)
    if not include_all_branches:
        return [default_branch]

    branches: list[str] = []
    seen: set[str] = set()
    if default_branch:
        branches.append(default_branch)
        seen.add(default_branch)

    start = 0
    while True:
        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches",
            params={"limit": 100, "start": start},
        )
        values = payload.get("values", []) or []
        for branch in values:
            branch_name = str(branch.get("displayId") or "").strip()
            if not branch_name or branch_name in seen:
                continue
            seen.add(branch_name)
            branches.append(branch_name)
        if payload.get("isLastPage", True):
            break
        start = int(payload.get("nextPageStart") or 0)
    return branches or ([default_branch] if default_branch else [])


def _mask_clone_url(url: str) -> str:
    split = urlsplit(url)
    host = split.hostname or split.netloc
    netloc = host
    if split.port:
        netloc = f"{host}:{split.port}"
    return urlunsplit((split.scheme, netloc, split.path, "", ""))


def _normalize_allowed_repos(config: dict) -> list[dict[str, Any]]:
    entries = []
    for entry in config.get("bitbucket_allowed_repos") or []:
        if isinstance(entry, str):
            if "/" not in entry:
                continue
            project_key, repo_slug = entry.split("/", 1)
            entries.append({"project_key": project_key.strip(), "repo_slug": repo_slug.strip(), "enabled": True})
            continue
        if isinstance(entry, dict):
            project_key = str(entry.get("project_key") or entry.get("project") or "").strip()
            repo_slug = str(entry.get("repo_slug") or entry.get("slug") or "").strip()
            if project_key and repo_slug:
                entries.append(
                    {
                        "project_key": project_key,
                        "repo_slug": repo_slug,
                        "enabled": bool(entry.get("enabled", True)),
                        "label": entry.get("label") or f"{project_key}/{repo_slug}",
                    }
                )
    return entries


def _is_repo_allowed(context: ToolContext, project_key: str, repo_slug: str) -> bool:
    allowed = _normalize_allowed_repos(context.project_config)
    if not allowed:
        return False
    for entry in allowed:
        if entry["project_key"].lower() == project_key.lower() and entry["repo_slug"].lower() == repo_slug.lower():
            return bool(entry.get("enabled", True))
    return False


def _commit_summary(commit: dict[str, Any]) -> dict[str, Any]:
    author = commit.get("author") or {}
    return {
        "id": commit.get("id"),
        "display_id": commit.get("displayId"),
        "message": commit.get("message"),
        "author_name": author.get("name"),
        "author_email": author.get("emailAddress"),
        "author_timestamp": commit.get("authorTimestamp"),
    }


async def _resolve_project_for_sync(context: ToolContext, params: dict[str, Any]) -> Project | None:
    if context.db is None:
        return None
    requested_project_id = str(params.get("project_id") or "").strip()
    if requested_project_id:
        project = await context.db.get(Project, requested_project_id)
        if project:
            return project
        result = await context.db.execute(select(Project).where(Project.name == requested_project_id))
        project = result.scalar_one_or_none()
        if project:
            return project
    configured_project_id = str(context.project_config.get("project_id") or "").strip()
    if configured_project_id:
        project = await context.db.get(Project, configured_project_id)
        if project:
            return project
    project_ids = context.project_ids or []
    if len(project_ids) == 1:
        return await context.db.get(Project, project_ids[0])
    return None


def _interesting_repo_paths(paths: list[str]) -> list[str]:
    interesting: list[str] = []
    seen: set[str] = set()
    patterns = (
        "readme.md",
        ".md",
        "chart.yaml",
        "values.yaml",
        "values.yml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "dockerfile",
        ".tf",
        ".ini",
        ".yaml",
        ".yml",
    )
    for path in paths:
        lowered = path.lower()
        if not lowered:
            continue
        if not any(token in lowered for token in patterns):
            continue
        if path in seen:
            continue
        seen.add(path)
        interesting.append(path)
        if len(interesting) >= 40:
            break
    return interesting
