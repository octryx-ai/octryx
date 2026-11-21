"""Link a ``git_repository`` source saved without a connection to the one connection that can read it.

The repository forms (Work › Repositories, Knowledge › Add source) have no connection picker, so a private
``github.com`` repository may be saved without ``connection_id``; read anonymously, it would end ``source_not_found``.
A source without a link is therefore resolved against the Workspace's connections:

- **candidates** (:func:`git_connection_candidates`): the connections available in the Workspace, active, with their
  ``knowledge`` use on and the repository path inside that use's scope (``linked_use.deviation_refusal``, as a linked
  read checks it) - for a Bitbucket connection also inside its bound repositories, the keys the Bitbucket route plan
  already reads an unlinked ``bitbucket.org`` source with (one bound elsewhere stays refused) -, that carry a
  credential (a GitHub connection without a token reads anonymously - linking it changes
  nothing) and serve the repository's host: a GitHub connection on ``api.github.com`` for ``github.com``, a Bitbucket
  Cloud connection for ``bitbucket.org``, a Bitbucket Data Center connection whose URL is the source's ``host_base``;
- exactly one: the source is linked to it through the configure path (``git_bitbucket.bind_repository_scope``) and the
  link is audited (``knowledge_source.connection_auto_linked``: Workspace, connector key, connection id, repository
  path - never a URL with a credential or a secret);
- several: refused with ``connection_choice_required`` and the candidates (id, name, type), never a guess;
- none: unchanged (a public repository, read anonymously).

Saving (``service.configure_connector``) and the start of a run (``service_run.run_connector``, for a source still
unbound: no candidate at save, or its connection deleted) both use :func:`auto_link_connection`; an explicit
``connection_id`` never comes here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.atlassian_auth_modes import BITBUCKET, is_bitbucket_cloud

from .....models import AuditLog, ConnectorNamedConnection
from ....github_url import normalize_github_api_base_url
from ....named_connections.contract import scope_key
from ....named_connections.descriptors import descriptor_of
from ....named_connections.grants import available_rows, has_credentials
from ....named_connections.linked_use import USE_KNOWLEDGE, deviation_refusal
from ...ledger.errors import InvalidEvidenceRequestError
from .contract import REASON_CONNECTION_CHOICE_REQUIRED, ConnectorError
from .git_bitbucket import GITHUB_CONNECTOR, repository_key
from .git_config import FETCH_REMOTE_GIT, HOST_BASE, HOST_KIND
from .git_hosts import BITBUCKET_CLOUD, GITHUB, HOST_BITBUCKET_DATACENTER, datacenter_base, parse_repository_url

AUTO_LINK_AUDIT_ACTION = "knowledge_source.connection_auto_linked"
_FIELDS = ("fetch_mode", "ref", "include_globs", "exclude_globs", "max_files", "max_file_bytes")


class ConnectionChoiceRequiredError(ConnectorError):
    """Several connections could read the repository; ``candidates`` are ``{id, name, type}`` only."""

    def __init__(self, candidates: list[dict[str, str]]) -> None:
        super().__init__(REASON_CONNECTION_CHOICE_REQUIRED)
        self.candidates = candidates


def _target(scope: dict) -> tuple[str, str, str | None] | None:
    """``(connection type, repository path, Data Center base)`` of a stored remote scope, else ``None``."""
    if not scope.get("remote") or scope.get("fetch_mode") != FETCH_REMOTE_GIT:
        return None
    if scope.get(HOST_KIND) == HOST_BITBUCKET_DATACENTER:
        key, base = repository_key(scope), scope.get(HOST_BASE)
        return (BITBUCKET, key, str(base)) if key and base else None
    try:
        location = parse_repository_url(scope.get("remote"), known_host_only=True)
    except InvalidEvidenceRequestError:
        return None
    if location.host is GITHUB:
        return GITHUB_CONNECTOR, location.path, None
    if location.host is BITBUCKET_CLOUD:
        return BITBUCKET, location.path, None
    return None


def _binds(row: ConnectorNamedConnection, tool: str, path: str) -> bool:
    """A Bitbucket connection binds the repository (itself or its project/workspace); GitHub: its knowledge scope
    decides alone."""
    if tool != BITBUCKET:
        return True
    descriptor = descriptor_of(tool)
    bound = {scope_key(tool, item) for item in row.bound_scopes or ()}
    key = scope_key(tool, path)
    return any(candidate in bound for candidate in (descriptor.binding.candidates(key) if descriptor else (key,)))


def _serves(tool: str, config: dict, base: str | None) -> bool:
    if tool == GITHUB_CONNECTOR:
        return normalize_github_api_base_url(config.get("github_url")) == GITHUB.api_base
    if base is None:
        return is_bitbucket_cloud(config)
    return not is_bitbucket_cloud(config) and datacenter_base(config.get("bitbucket_url")) == base


async def git_connection_candidates(db: AsyncSession, project_id: str,
                                    scope: dict | None) -> list[ConnectorNamedConnection]:
    """The connections an unlinked source of ``scope`` could be linked to (module doc), by name."""
    target = _target(dict(scope or {}))
    if target is None:
        return []
    tool, path, base = target
    return [row for row, grant in await available_rows(db, (tool,), project_id)
            if grant.is_active and deviation_refusal(grant, USE_KNOWLEDGE, tool, (path,)) is None
            and _binds(row, tool, path) and has_credentials(tool, row.config)
            and _serves(tool, dict(row.config or {}), base)]


def describe_candidates(rows: list[ConnectorNamedConnection]) -> list[dict[str, str]]:
    return [{"id": str(row.id), "name": str(row.name or ""), "type": str(row.tool_name)} for row in rows]


async def auto_link_connection(db: AsyncSession, project_id: str, scope: dict | None) -> str | None:
    """The one candidate's id; ``None`` without any; :class:`ConnectionChoiceRequiredError` for several."""
    rows = await git_connection_candidates(db, project_id, scope)
    if len(rows) > 1:
        raise ConnectionChoiceRequiredError(describe_candidates(rows))
    return str(rows[0].id) if rows else None


def unlinked_scope(repository_url: object) -> dict:
    """The remote part of the scope an unlinked source of ``repository_url`` gets (a known public host); an invalid or
    unknown URL is :class:`InvalidEvidenceRequestError`, as on save."""
    location = parse_repository_url(repository_url, known_host_only=True)
    return {"remote": location.url, "fetch_mode": FETCH_REMOTE_GIT}


def link_fields(scope: dict) -> dict:
    """The configure fields of a validated unlinked scope, for ``bind_repository_scope`` with the found connection."""
    return {"repository_url": scope.get("remote"), **{name: scope.get(name) for name in _FIELDS}}


def record_auto_link(db: AsyncSession, *, actor_id: str, project_id: str, connector_id: str | None,
                     connector_key: str, connection_id: str, scope: dict) -> None:
    target = _target(scope)
    db.add(AuditLog(
        user_id=actor_id, action=AUTO_LINK_AUDIT_ACTION, resource_type="knowledge_source_connector",
        resource_id=connector_id,
        details={"workspace_id": project_id, "connector_key": connector_key, "connection_id": connection_id,
                 "repository": target[1] if target else None},
    ))


__all__ = [
    "AUTO_LINK_AUDIT_ACTION",
    "ConnectionChoiceRequiredError",
    "auto_link_connection",
    "describe_candidates",
    "git_connection_candidates",
    "link_fields",
    "record_auto_link",
    "unlinked_scope",
]
