"""Find the repositories a Bitbucket connection can read, to register them as Knowledge repository sources.

Stage A visibility: a connection lists exactly what its own technical client sees (no per-user filtering), and
only a Workspace author may ask (the route authorizes). The connection must be usable in the Workspace (available,
active, its ``knowledge`` use on: ``sync/git_bitbucket.usable_connection``); every refusal is a fixed reason.

- :func:`repository_connections`: the Bitbucket connections usable for Knowledge in a Workspace;
- :func:`list_repositories`: one page (at most 25) of the connection's repositories, optionally searched by name
  (``PROJ/`` or ``PROJ/name`` narrows a Data Center listing to one project):

  * Data Center: ``GET {base}/rest/api/1.0/repos?name=&start=&limit=`` (``/projects/{KEY}/repos`` for a project),
    paged by ``isLastPage`` / ``nextPageStart``;
  * Cloud: ``GET https://api.bitbucket.org/2.0/repositories?role=member&q=name~"..."``, paged by ``page``;

- :func:`default_branch`: one repository's default branch, read lazily when a repository is picked;
- :func:`target_workspaces`: the Workspaces the caller authors where the connection is usable ("make available in").

Every request goes through the pinned egress transport of the ``bitbucket`` connection type with the connection's
own sign-in (``atlassian_auth.credential_auth``: Basic, a personal access token, or the OpenID Connect client
credentials grant's Bearer). Only keys, slugs, names, web URLs and branch names are returned; never a credential,
a response body or a header.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.atlassian_auth_modes import BITBUCKET, is_bitbucket_cloud
from app.services.knowledge.sources.sync.git_cloud import ConnectedGitConnection

from ....models import ConnectorNamedConnection, Project
from ....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY, KnowledgeSourceConnector
from ...access_control import _user_is_admin
from ...atlassian_auth import credential_auth
from ...named_connections.grants import grant_for
from ...named_connections.linked_use import USE_KNOWLEDGE, deviation_refusal
from ...oidc_client_credentials import OidcTokenError
from ...outbound_egress import CONNECTION_BITBUCKET, EgressRefusedError, egress_transport
from ...project.service import get_project_access_details
from ..access.authorization import AUTHOR_PROJECT_ROLES
from .sync.contract import (
    REASON_EGRESS_REFUSED,
    REASON_REPOSITORY_NOT_ON_CONNECTION_HOST,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
    ConnectorError,
)
from .sync.git_bitbucket import bitbucket_connection_config, connected_from_config, usable_connection
from .sync.git_config import ACCESS_MODE
from .sync.git_hosts import datacenter_host
from .sync.http import reason_for_status

PAGE_SIZE = 25
MAX_START = 100_000
MAX_QUERY_CHARS = 100
CLOUD_API = "https://api.bitbucket.org/2.0"
TIMEOUT_SECONDS = 30.0
_PROJECT_QUERY = re.compile(r"^(~?[A-Za-z0-9_]{1,128})/(.*)$")
_PROJECT_KEY = re.compile(r"^~?[A-Za-z0-9_]{1,128}$")
_SLUG = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_NAME_CHARS = 200


def _deployment(config: dict) -> str:
    return "cloud" if is_bitbucket_cloud(config) else "datacenter"


async def repository_connections(db: AsyncSession, project_id: str) -> list[dict[str, Any]]:
    """The Bitbucket connections a Knowledge repository source of ``project_id`` may read with, by name."""
    rows = (await db.execute(
        select(ConnectorNamedConnection).where(ConnectorNamedConnection.tool_name == BITBUCKET)
        .order_by(ConnectorNamedConnection.name)
    )).scalars().all()
    listed = []
    for row in rows:
        grant = await grant_for(db, row, project_id)
        if grant is None or not grant.is_active or deviation_refusal(grant, USE_KNOWLEDGE, BITBUCKET, ()) is not None:
            continue
        config = dict(row.config or {})
        listed.append({"id": row.id, "name": row.name, "type": BITBUCKET, "deployment": _deployment(config),
                       "host": (urlsplit(str(config.get("bitbucket_url") or "")).hostname or "").lower() or None})
    return listed


async def _connection(db: AsyncSession, project_id: str, connection_id: str) -> ConnectedGitConnection:
    row = await usable_connection(db, project_id, connection_id)
    if row.tool_name != BITBUCKET:
        raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST)
    return connected_from_config(await bitbucket_connection_config(db, row))


async def _get_json(connection: ConnectedGitConnection, url: str, params: dict[str, Any],
                    transport: httpx.AsyncBaseTransport | None) -> tuple[int, Any]:
    if connection.credential is not None:
        auth: httpx.Auth = credential_auth(connection.credential, transport=transport)
    else:
        auth = httpx.BasicAuth(*connection.auth)  # type: ignore[misc] - Cloud always has its pair
    try:
        async with httpx.AsyncClient(
            transport=egress_transport(CONNECTION_BITBUCKET, inner=transport), timeout=TIMEOUT_SECONDS,
            follow_redirects=False, auth=auth,
        ) as client:
            response = await client.get(url, params=params, headers={"Accept": "application/json"})
    except EgressRefusedError:
        raise ConnectorError(REASON_EGRESS_REFUSED) from None
    except OidcTokenError:
        raise ConnectorError(REASON_SOURCE_UNAUTHORIZED) from None
    except httpx.HTTPError:
        raise ConnectorError(REASON_SOURCE_UNAVAILABLE) from None
    if response.status_code in (204, 404):
        return response.status_code, None
    if response.status_code != 200:
        raise ConnectorError(reason_for_status(response.status_code))
    try:
        return 200, response.json()
    except ValueError:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None


def _text(value: object, limit: int = _MAX_NAME_CHARS) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


async def _registered(db: AsyncSession, project_id: str, connection_id: str) -> dict[str, dict[str, Any]]:
    rows = (await db.execute(select(KnowledgeSourceConnector).where(
        KnowledgeSourceConnector.project_id == project_id,
        KnowledgeSourceConnector.kind == CONNECTOR_KIND_GIT_REPOSITORY,
        KnowledgeSourceConnector.connection_id == connection_id,
    ))).scalars().all()
    return {str((row.scope or {}).get("remote") or ""): {
        "connector_key": row.connector_key, "access_mode": (row.scope or {}).get(ACCESS_MODE)} for row in rows}


def _bounded(q: object, start: object, limit: object) -> tuple[str, int, int]:
    query = _text(q, MAX_QUERY_CHARS) if q is not None else ""
    first = start if type(start) is int and 0 <= start <= MAX_START else 0
    size = limit if type(limit) is int and 1 <= limit <= PAGE_SIZE else PAGE_SIZE
    return query, first, size


async def list_repositories(
    db: AsyncSession, project_id: str, connection_id: str, *, q: object = None, start: object = 0,
    limit: object = PAGE_SIZE, transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """One page of the connection's repositories (see the module doc); ``registered`` marks this Workspace's."""
    connection = await _connection(db, project_id, connection_id)
    query, first, size = _bounded(q, start, limit)
    if connection.base_url is None:
        page = await _cloud_page(connection, query, first, size, transport)
    else:
        page = await _datacenter_page(connection, query, first, size, transport)
    registered = await _registered(db, project_id, connection_id)
    for item in page["repositories"]:
        item["registered"] = registered.get(item["repository_url"])
    return page


async def _datacenter_page(connection: ConnectedGitConnection, query: str, start: int, size: int,
                           transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    assert connection.base_url is not None
    host = datacenter_host(connection.base_url)
    params: dict[str, Any] = {"start": start, "limit": size}
    narrowed = _PROJECT_QUERY.fullmatch(query)
    name_filter = ""
    if narrowed:  # "PROJ/" or "PROJ/name": that project's repositories, the name matched within the page
        key = narrowed[1] if narrowed[1].startswith("~") else narrowed[1].upper()
        url = f"{host.api_base}/projects/{quote(key, safe='~')}/repos"
        name_filter = narrowed[2].strip().lower()
    else:
        url = f"{host.api_base}/repos"
        if query:
            params["name"] = query
    status, payload = await _get_json(connection, url, params, transport)
    if status != 200 or not isinstance(payload, dict):
        return {"repositories": [], "start": start, "limit": size, "next_start": None, "is_last_page": True}
    repositories = []
    for value in payload.get("values") or []:
        if not isinstance(value, dict):
            continue
        project = _text((value.get("project") or {}).get("key") if isinstance(value.get("project"), dict) else "")
        slug, name = _text(value.get("slug")), _text(value.get("name"))
        if not _PROJECT_KEY.fullmatch(project) or not _SLUG.fullmatch(slug):
            continue
        if name_filter and name_filter not in name.lower() and name_filter not in slug.lower():
            continue
        path = f"{project if project.startswith('~') else project.upper()}/{slug.lower()}"
        repository_url = host.repository_url(path)
        repositories.append({"project_key": path.split("/", 1)[0], "slug": slug.lower(), "name": name or slug,
                             "repository_url": repository_url, "web_url": f"{repository_url}/browse"})
    last = payload.get("isLastPage") is not False
    following = payload.get("nextPageStart")
    next_start = following if not last and type(following) is int and start < following <= MAX_START else None
    return {"repositories": repositories, "start": start, "limit": size, "next_start": next_start,
            "is_last_page": next_start is None}


async def _cloud_page(connection: ConnectedGitConnection, query: str, start: int, size: int,
                      transport: httpx.AsyncBaseTransport | None) -> dict[str, Any]:
    params: dict[str, Any] = {"role": "member", "pagelen": size, "page": start // size + 1, "sort": "full_name"}
    if query:
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        params["q"] = f'name ~ "{escaped}"'
    status, payload = await _get_json(connection, f"{CLOUD_API}/repositories", params, transport)
    if status != 200 or not isinstance(payload, dict):
        return {"repositories": [], "start": start, "limit": size, "next_start": None, "is_last_page": True}
    repositories = []
    for value in payload.get("values") or []:
        if not isinstance(value, dict):
            continue
        workspace, _, slug = _text(value.get("full_name")).partition("/")
        if not workspace or not _SLUG.fullmatch(slug):
            continue
        branch = value.get("mainbranch") if isinstance(value.get("mainbranch"), dict) else {}
        repository_url = f"https://bitbucket.org/{workspace.lower()}/{slug.lower()}"
        repositories.append({"project_key": workspace.lower(), "slug": slug.lower(),
                             "name": _text(value.get("name")) or slug, "repository_url": repository_url,
                             "web_url": repository_url, "default_branch": _text(branch.get("name")) or None})
    next_start = start + size if payload.get("next") and start + size <= MAX_START else None
    return {"repositories": repositories, "start": start, "limit": size, "next_start": next_start,
            "is_last_page": next_start is None}


async def default_branch(
    db: AsyncSession, project_id: str, connection_id: str, project_key: str, slug: str, *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """The repository's default branch name, or ``None`` when it has none (an empty repository)."""
    if not _PROJECT_KEY.fullmatch(project_key or "") or not _SLUG.fullmatch(slug or ""):
        raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST)
    connection = await _connection(db, project_id, connection_id)
    if connection.base_url is None:
        url = f"{CLOUD_API}/repositories/{quote(project_key.lower(), safe='')}/{quote(slug.lower(), safe='')}"
        status, payload = await _get_json(connection, url, {}, transport)
        branch = payload.get("mainbranch") if status == 200 and isinstance(payload, dict) else None
        return _text(branch.get("name")) or None if isinstance(branch, dict) else None
    host = datacenter_host(connection.base_url)
    key = project_key if project_key.startswith("~") else project_key.upper()
    base = f"{host.api_base}/projects/{quote(key, safe='~')}/repos/{quote(slug.lower(), safe='')}"
    for path in ("/default-branch", "/branches/default"):
        status, payload = await _get_json(connection, base + path, {}, transport)
        if status == 200 and isinstance(payload, dict):
            return _text(payload.get("displayId")) or None
    return None


async def target_workspaces(db: AsyncSession, user_id: str, connection_id: str, current: str) -> list[dict[str, Any]]:
    """The Workspaces ``user_id`` authors where the connection is usable for Knowledge, the current one first."""
    row = await db.get(ConnectorNamedConnection, connection_id)
    if row is None or row.tool_name != BITBUCKET:
        return []
    if await _user_is_admin(db, user_id):
        projects = (await db.execute(select(Project.id, Project.name).where(Project.is_active.is_(True))
                                     .order_by(Project.name))).all()
        candidates = [(str(project_id), str(name)) for project_id, name in projects]
    else:
        candidates = [(str(item["id"]), str(item.get("name") or item["id"]))
                      for item in await get_project_access_details(user_id, db)
                      if str(item.get("role") or "") in AUTHOR_PROJECT_ROLES]
    listed = []
    for project_id, name in candidates:
        grant = await grant_for(db, row, project_id)
        if grant is None or not grant.is_active or deviation_refusal(grant, USE_KNOWLEDGE, BITBUCKET, ()) is not None:
            continue
        listed.append({"id": project_id, "name": name, "current": project_id == current})
    return sorted(listed, key=lambda item: (not item["current"], item["name"].lower()))


__all__ = ["PAGE_SIZE", "default_branch", "list_repositories", "repository_connections", "target_workspaces"]
