"""Whether a configured scope lies inside its Workspace connection's own allowlist (``config.py`` module doc)."""

from __future__ import annotations

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_KIND_KUBERNETES,
    CONNECTOR_KIND_SERVICENOW,
)
from .confluence_scope import scope_space_keys
from .connections import PublicGitConnection, SourceConnection
from .git_config import FETCH_LOCAL_SNAPSHOT
from .git_hosts import GIT_HOSTS
from .kinds import KINDS
from .servicenow_connection import ServiceNowConnection
from .servicenow_scope import scope_tables


def scope_within_connection(
    kind: str, scope: dict, connection: SourceConnection | ServiceNowConnection | PublicGitConnection
) -> bool:
    """True when every configured space, project or table is inside the connection's own allowlist.

    A ``git_repository`` has no connection allowlist: a ``remote_git`` scope must name a known host;
    a ``local_snapshot`` scope fetches nothing (its run is refused as ``snapshot_upload_required``).
    """
    if connection.kind != kind:
        return False
    within = KINDS[kind].within if kind in KINDS else None
    if within is not None:
        return within(scope, connection)
    if kind == CONNECTOR_KIND_GIT_REPOSITORY:
        if scope.get("fetch_mode") == FETCH_LOCAL_SNAPSHOT:
            return True
        base = getattr(connection, "base_url", None)
        if base:  # a Data Center repository: on its linked connection's own URL only
            return str(scope.get("remote") or "").startswith(f"{base}/")
        return str(scope.get("remote") or "").startswith(tuple(f"https://{host}/" for host in GIT_HOSTS))
    if kind == CONNECTOR_KIND_KUBERNETES:
        # Every configured namespace inside the connection's own namespaces (all, when it names none).
        allowed_namespaces = getattr(connection, "allowed_namespaces", None)
        return allowed_namespaces is None or set(scope.get("namespaces") or ()) <= allowed_namespaces
    if kind == CONNECTOR_KIND_SERVICENOW:
        keys = scope_tables(scope)
    elif kind == CONNECTOR_KIND_CONFLUENCE:
        keys = scope_space_keys(scope)  # a page tree's space must be allowed like a whole space
    else:
        keys = tuple(scope.get("spaces") or scope.get("project_keys") or ())
    allowed = connection.allowed_scopes
    if allowed is None:
        return kind in (CONNECTOR_KIND_JIRA, CONNECTOR_KIND_SERVICENOW) and bool(keys)
    return bool(keys) and all(str(key).upper() in allowed for key in keys)
