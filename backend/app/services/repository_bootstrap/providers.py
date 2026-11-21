from __future__ import annotations

from typing import Any

import httpx

from app.services.atlassian_auth_modes import BITBUCKET, SCHEME_BASIC
from app.services.outbound_egress import CONNECTION_BITBUCKET, CONNECTION_GITHUB, egress_transport

from ..atlassian_auth import AtlassianCredential, credential_auth, resolve_credential
from ..git_http_auth import basic_header_env, bearer_header_env
from ..github_url import normalize_github_api_base_url
from ..oidc_token_cache import access_token


def github_api_base(project_config: dict[str, Any]) -> str:
    return normalize_github_api_base_url(project_config.get("github_url"))


def github_token(project_config: dict[str, Any]) -> str:
    return str(project_config.get("github_token") or "").strip()


async def create_github_repository(
    *,
    project_config: dict[str, Any],
    config: dict[str, Any],
    repo_name: str,
) -> dict[str, Any]:
    token = github_token(project_config)
    if not token:
        raise ValueError("GitHub token is required to create a repository")
    base_url = github_api_base(project_config)
    owner = str(config.get("github_owner") or project_config.get("github_owner") or "").strip()
    owner_type = str(config.get("github_owner_type") or "org").strip().lower() or "org"
    payload = {
        "name": repo_name,
        "private": str(config.get("remote_visibility") or "private") != "public",
        "auto_init": False,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if owner and owner_type in {"org", "organization"}:
        url = f"{base_url}/orgs/{owner}/repos"
    else:
        url = f"{base_url}/user/repos"
    async with httpx.AsyncClient(timeout=30, transport=egress_transport(CONNECTION_GITHUB)) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    clone_url = str(data.get("clone_url") or "").strip()
    return {
        "provider": "github",
        "repository_name": str(data.get("name") or repo_name),
        "full_name": str(data.get("full_name") or ""),
        "html_url": str(data.get("html_url") or ""),
        "clone_url": clone_url,
        # The token never goes into the remote URL (argv, .git/config): the initial push sends it as a header from
        # the environment (git_http_auth). Callers pop "git_env" before anything leaves the process.
        **({"git_env": basic_header_env(clone_url, "x-access-token", token)} if clone_url else {}),
    }


def bitbucket_base_url(project_config: dict[str, Any]) -> str:
    return str(project_config.get("bitbucket_url") or "").strip().rstrip("/")


def bitbucket_credential(project_config: dict[str, Any]) -> AtlassianCredential:
    """The connection's sign-in (``atlassian_auth``: ``cloud_api_token``, ``basic``, ``bearer_pat``, OpenID Connect)."""
    credential = resolve_credential(BITBUCKET, project_config)
    if credential is None:
        raise ValueError("Bitbucket username and token/password are required to create a repository")
    return credential


def bitbucket_credentials(project_config: dict[str, Any]) -> tuple[str, str]:
    """``(username, secret)`` of a Basic sign-in; a Bearer sign-in has no username/password pair."""
    credential = bitbucket_credential(project_config)
    if credential.scheme != SCHEME_BASIC:
        raise ValueError("This Bitbucket connection signs in with a Bearer token, not a username and password")
    return credential.principal, credential.secret


async def create_bitbucket_repository(
    *,
    project_config: dict[str, Any],
    config: dict[str, Any],
    repo_name: str,
) -> dict[str, Any]:
    if str(project_config.get("bitbucket_deployment") or "").strip().lower() == "cloud":
        raise ValueError("Creating a repository is not available for Bitbucket Cloud connections yet")
    base_url = bitbucket_base_url(project_config)
    if not base_url:
        raise ValueError("Bitbucket URL is required to create a repository")
    project_key = str(config.get("bitbucket_project_key") or "").strip()
    if not project_key:
        raise ValueError("bitbucket_project_key is required for Bitbucket repository bootstrap")

    credential = bitbucket_credential(project_config)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    payload = {"name": repo_name, "scmId": "git", "forkable": True}
    async with httpx.AsyncClient(
        timeout=30, auth=credential_auth(credential), transport=egress_transport(CONNECTION_BITBUCKET)
    ) as client:
        response = await client.post(
            f"{base_url}/rest/api/1.0/projects/{project_key}/repos",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    clone_links = (data.get("links") or {}).get("clone") or []
    clone_url = ""
    for link in clone_links:
        if str(link.get("name") or "").lower() == "http":
            clone_url = str(link.get("href") or "").strip()
            break
    if not clone_url:
        clone_url = f"{base_url}/scm/{project_key}/{data.get('slug')}.git"

    # Never a credential in the remote URL: Basic and Bearer both go as a header from the environment.
    if credential.scheme == SCHEME_BASIC:
        git_env = basic_header_env(clone_url, credential.principal, credential.secret)
    else:
        token = credential.secret if credential.oidc is None else await access_token(credential.oidc)
        git_env = bearer_header_env(clone_url, token)
    return {
        "provider": "bitbucket",
        "repository_name": str(data.get("slug") or repo_name),
        "full_name": f"{project_key}/{data.get('slug') or repo_name}",
        "html_url": str((((data.get("links") or {}).get("self") or [{}])[0]).get("href") or ""),
        "clone_url": clone_url,
        "project_key": project_key,
        "repo_slug": str(data.get("slug") or repo_name),
        "git_env": git_env,
    }
