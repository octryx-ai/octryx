"""A repository for runs, added through a connection.

Work › Repositories › "Add a repository for runs": the Workspace's GitHub, GitLab or Bitbucket connection, the
repository (``owner/repo``), its base branch, the rights a run has in it and, optionally, its test command. One path
for the demo seed and for real use.

- :func:`detect` reads what the repository holds through the connection: whether it exists, and its apps (every
  ``.octryx/environment.json``). GitHub (and GitHub Enterprise, and the local fake GitHub) is read
  through its tree API; for GitLab and Bitbucket the apps are found when the first run prepares the repository
  (the launcher's preparation report, ``workspace/run_app.remember_apps``).
- :func:`add` writes the record: provider and clone URL from the connection, the rights (read, branch, write and pull
  request on by default, each can be switched off), the apps and the coding setup. A connection that is already bound
  to repositories gets this one bound too; an unbound connection already serves the Workspace, and binding it would
  take it away from the Workspace's other repositories (the binding dialog's warning), so it stays unbound.

The record's ``repo_root`` is its clone URL: there is no server checkout, and code navigation stays off (``index``
false) until the repository is bound to a Knowledge source or a launcher uploads it.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, CodeRepository, ConnectorNamedConnection, User
from ...github_url import github_web_base_url, normalize_github_api_base_url
from ...named_connections.contract import DEFAULT_CONNECTION_NAME
from ...outbound_egress import CONNECTION_GITHUB, egress_transport
from ...workflow_runs.workspace.run_app import APP_ENVIRONMENT_FILE, RECORD_APPS_KEY, reported_apps
from ..intake.connections import connection_config_of, workspace_connections
from .record import save_setup

CONNECTORS = ("github", "gitlab", "bitbucket")
RIGHTS = ("read", "branch", "write", "pr")
_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}(/[A-Za-z0-9._-]{1,100}){1,2}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


def _refused(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _repository(raw: Any) -> str:
    text = str(raw or "").strip().strip("/").removesuffix(".git")
    if not _REPOSITORY.match(text) or ".." in text:
        raise _refused("repository_invalid", "The repository is owner/name, e.g. demo-org/demo-shop.")
    return text


def _branch(raw: Any) -> str:
    text = str(raw or "").strip() or "main"
    if not _BRANCH.match(text) or ".." in text or text.startswith(("-", "/")):
        raise _refused("branch_invalid", "The base branch is a branch name, e.g. main.")
    return text


async def connections(db: AsyncSession, workspace_id: str) -> list[dict[str, Any]]:
    """The Workspace's code connections a run repository can use: ``[{id, name, connector, bound_scopes}]``."""
    listed = []
    for connector in CONNECTORS:
        for row in await workspace_connections(db, workspace_id, connector):
            entry = {"id": row["id"], "name": row["name"], "connector": connector,
                     "bound_scopes": row.get("bound_scopes") or []}
            # The Workspace's default entry of a connector that is a default connection: list it by
            # that connection's own id and name, never as "default".
            alias = next(iter(row.get("aliases") or []), None)
            named = await db.get(ConnectorNamedConnection, alias) if alias else None
            if named is not None:
                if any(other["id"] == named.id for other in listed):
                    continue
                entry.update(id=named.id, name=named.name, bound_scopes=sorted(named.bound_scopes or []))
            elif row.get("default"):
                entry["name"] = f"{connector.capitalize()} (default connection)"
            if not any(other["id"] == entry["id"] for other in listed):
                listed.append(entry)
    return listed


async def _connection(db: AsyncSession, workspace_id: str,
                      connection_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(listing entry, effective config with its secret)`` of one of the Workspace's code connections."""
    entry = next((row for row in await connections(db, workspace_id) if row["id"] == connection_id), None)
    if entry is None:
        raise _refused("connection_not_found",
                       "Choose one of this Workspace's GitHub, GitLab or Bitbucket connections.")
    config = await connection_config_of(db, workspace_id, entry["connector"], connection_id)
    if config is None:
        raise _refused("connection_not_found", "That connection is gone; choose another.")
    return entry, config


def clone_url(connector: str, config: dict[str, Any], repository: str) -> str:
    """The repository's clone URL as the connection names its host."""
    if connector == "github":
        web = github_web_base_url(config.get("github_url")) or "https://github.com"
        return f"{web}/{repository}.git"
    if connector == "gitlab":
        return f"{str(config.get('gitlab_url') or 'https://gitlab.com').rstrip('/')}/{repository}.git"
    if str(config.get("bitbucket_deployment") or "datacenter") == "cloud":
        return f"https://bitbucket.org/{repository}.git"
    project, slug = repository.split("/", 1)
    return f"{str(config.get('bitbucket_url') or '').rstrip('/')}/scm/{project.lower()}/{slug}.git"


async def _github_tree(config: dict[str, Any], repository: str, branch: str) -> list[str] | None:
    """The repository's file paths at ``branch`` (``None`` when the repository or branch does not exist)."""
    api = normalize_github_api_base_url(config.get("github_url"))
    headers = {"Accept": "application/vnd.github+json"}
    if config.get("github_token"):
        headers["Authorization"] = f"Bearer {config['github_token']}"
    async with httpx.AsyncClient(timeout=20, transport=egress_transport(CONNECTION_GITHUB)) as client:
        response = await client.get(f"{api}/repos/{repository}/git/trees/{quote(branch, safe='')}",
                                    params={"recursive": "1"}, headers=headers)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise _refused("repository_unreadable",
                       f"The connection could not read {repository} (HTTP {response.status_code}).", 409)
    return [str(entry.get("path") or "") for entry in response.json().get("tree") or [] if entry.get("type") == "blob"]


async def detect(db: AsyncSession, workspace_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """What the repository holds: ``{exists, apps, apps_found_at}`` (``exists`` ``None``: not checked here)."""
    entry, config = await _connection(db, workspace_id, str(body.get("connection_id") or ""))
    repository, branch = _repository(body.get("repository")), _branch(body.get("base_branch"))
    if entry["connector"] != "github":
        return {"repository": repository, "base_branch": branch, "exists": None, "apps": [],
                "apps_found_at": "first_run"}
    try:
        paths = await _github_tree(config, repository, branch)
    except httpx.HTTPError as error:
        raise _refused("repository_unreadable", f"The connection could not be reached: {type(error).__name__}.",
                       409) from None
    if paths is None:
        return {"repository": repository, "base_branch": branch, "exists": False, "apps": [], "apps_found_at": "now"}
    files = [path for path in paths if path == APP_ENVIRONMENT_FILE or path.endswith(f"/{APP_ENVIRONMENT_FILE}")]
    return {"repository": repository, "base_branch": branch, "exists": True,
            "apps": reported_apps({RECORD_APPS_KEY: files}), "apps_found_at": "now"}


def _rights(raw: Any) -> dict[str, bool]:
    chosen = raw if isinstance(raw, dict) else {}
    return {right: bool(chosen.get(right, True)) for right in RIGHTS}


async def add(db: AsyncSession, *, user: User, workspace_id: str, body: dict[str, Any]) -> CodeRepository:
    """The Workspace's run repository through a connection (see the module doc); 409 when it exists already."""
    from ...code_intelligence.repository import create_code_repository

    entry, config = await _connection(db, workspace_id, str(body.get("connection_id") or ""))
    repository, branch = _repository(body.get("repository")), _branch(body.get("base_branch"))
    existing = (await db.execute(select(CodeRepository.id).where(
        CodeRepository.project_id == workspace_id, CodeRepository.name == repository))).first()
    if existing is not None:
        raise _refused("repository_exists", f"{repository} is already a repository of this Workspace.", 409)
    url = clone_url(entry["connector"], config, repository)
    apps = reported_apps({RECORD_APPS_KEY: [str(app.get("environment_file") or "") for app in body.get("apps") or []
                                            if isinstance(app, dict)]})
    created = await create_code_repository(db, {
        "project_id": workspace_id, "name": repository, "provider": entry["connector"], "default_branch": branch,
        "remote_url": url, "repo_root": url, "is_active": True,
        "description": str(body.get("description") or "").strip()[:500],
        "config_json": {"operation_policy": {**_rights(body.get("rights")), "index": False},
                        "created_from": "run_repository", "connection_id": entry["id"],
                        **({RECORD_APPS_KEY: apps} if apps else {})}})
    repo = await db.get(CodeRepository, created["id"])
    if entry["bound_scopes"] and entry["id"] != DEFAULT_CONNECTION_NAME:
        row = await db.get(ConnectorNamedConnection, entry["id"])
        if row is not None and repository.lower() not in {scope.lower() for scope in row.bound_scopes or []}:
            row.bound_scopes = sorted({*(row.bound_scopes or []), repository.lower()})
    test = str(body.get("test_command") or "").strip()
    if test:
        await save_setup(db, user=user, repo=repo, payload={"test_commands": [test], "pr_target_branch": branch})
    db.add(AuditLog(user_id=user.id, action="code_repository.run_repository_added", resource_type="code_repository",
                    resource_id=repo.id, details={"workspace_id": workspace_id, "repository": repository,
                                                  "connection_id": entry["id"], "rights": _rights(body.get("rights")),
                                                  "apps": len(apps), "test_command": bool(test)}))
    await db.commit()
    await db.refresh(repo)
    return repo


__all__ = ["CONNECTORS", "RIGHTS", "add", "clone_url", "connections", "detect"]
