"""Real entities for the policy builder's pickers and their names.

``GET …/catalog/entities`` lists, bounded and searchable (``q`` over id and name, ``limit`` per type):
Workspaces (with classification), users, platform roles and active identity groups (with member counts),
named connections (id, name, connector, Workspace or global scope, bound scopes), tools as objects (connector
family, risk, whether a call can change data or read logs) and model aliases (with their data-policy class).

Policies store ids (Cedar ``Workspace::"<id>"``, ``User::"<id>"``, connection ids); roles and groups are
stored by name (``principals`` builds ``Role::"<name>"``). :class:`NameIndex` resolves ids back to names for the
list sentences; an id that no longer exists stays visible as unknown instead of disappearing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorNamedConnection, IdentityGroup, Project, Role, User, UserGroup, UserRole
from ...models.runtime.named_connection import GLOBAL_SCOPE_KEY
from .catalog import connector_families

ENTITY_TYPES: tuple[str, ...] = (
    "workspaces", "users", "roles", "groups", "named_connections", "tools", "model_aliases", "connector_families",
)
MAX_LIMIT = 500
DEFAULT_LIMIT = 500
DEFAULT_CONNECTION = "default"
LOG_TOOLS_BY_ARGUMENT = frozenset({"run_kubectl", "aws_read_operation"})


def _matches(query: str, *values: Any) -> bool:
    return not query or any(query in str(value or "").lower() for value in values)


async def _workspaces(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    from ..model_gateway.data_policy.source import resolve_workspace_data_classification

    rows = (await db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.name))).scalars()
    picked = [row for row in rows if _matches(query, row.id, row.name)][:limit]
    items = []
    for project in picked:
        classification = await resolve_workspace_data_classification(db, project_id=project.id)
        items.append({"id": project.id, "name": project.name,
                      "classification": classification.classification if classification.resolved else None})
    return items


async def _users(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    rows = (await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.username))).scalars()
    return [{"id": row.id, "username": row.username, "display_name": row.display_name}
            for row in rows if _matches(query, row.id, row.username, row.display_name)][:limit]


async def _roles(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    counts = dict((await db.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id))).all())
    rows = (await db.execute(select(Role).order_by(Role.name))).scalars()
    return [{"name": row.name, "description": row.description or "", "member_count": int(counts.get(row.id, 0))}
            for row in rows if _matches(query, row.name, row.description)][:limit]


async def _groups(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    counts = dict((await db.execute(select(UserGroup.group_id, func.count()).group_by(UserGroup.group_id))).all())
    rows = (await db.execute(select(IdentityGroup).where(IdentityGroup.is_active.is_(True))
                             .order_by(IdentityGroup.name))).scalars()
    return [{"name": row.name, "description": row.description or "", "member_count": int(counts.get(row.id, 0))}
            for row in rows if _matches(query, row.name, row.description)][:limit]


async def _named_connections(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    stmt = (select(ConnectorNamedConnection, Project.name)
            .outerjoin(Project, Project.id == ConnectorNamedConnection.project_id)
            .order_by(ConnectorNamedConnection.tool_name, ConnectorNamedConnection.name))
    items = []
    for row, workspace_name in (await db.execute(stmt)).all():
        if not _matches(query, row.id, row.name, row.tool_name, workspace_name):
            continue
        items.append({"id": row.id, "name": row.name, "connector": row.tool_name,
                      "scope": "global" if row.scope_key == GLOBAL_SCOPE_KEY else "workspace",
                      "workspace_id": row.project_id, "workspace_name": workspace_name,
                      "bound_scopes": sorted(str(item) for item in row.bound_scopes or ())})
    return items[:limit]


def tool_items(query: str = "", limit: int = MAX_LIMIT) -> list[dict[str, Any]]:
    from ...tools.definitions import get_all_definitions, get_tool_definition_metadata
    from ..classification_tool_policy import LOG_READING_TOOLS, tool_connector_family

    items = []
    for name in sorted(get_all_definitions()):
        metadata = get_tool_definition_metadata(name)
        family = tool_connector_family(name)
        if not _matches(query, name, family, metadata.connector):
            continue
        items.append({
            "name": name, "connector_family": family, "connector": metadata.connector, "risk": metadata.risk,
            "mutates_state": bool(metadata.mutates_state or metadata.change_only
                                  or metadata.risk in {"write", "admin"}),
            "reads_logs": name in LOG_READING_TOOLS or name in LOG_TOOLS_BY_ARGUMENT,
        })
    return items[:limit]


async def _model_aliases(db: AsyncSession, query: str, limit: int) -> list[dict[str, Any]]:
    from ..model_gateway.data_policy.effects import gateway_aliases
    from .runtime import alias_approvals

    classes: dict[str, str] = {}
    for alias, data_policy_class in await gateway_aliases(db):
        classes.setdefault(alias, data_policy_class)
    approvals = await alias_approvals(db)  # "Approved for sensitive data" (the content route targets)
    return [{"alias": alias, "data_policy_class": classes[alias] or None,
             "approved_for": sorted(approvals.get(alias, ()))}
            for alias in sorted(classes) if _matches(query, alias)][:limit]


def _families(query: str, limit: int) -> list[dict[str, Any]]:
    return [{"id": family, "label": family_label(family)} for family in connector_families()
            if _matches(query, family, family_label(family))][:limit]


_FAMILY_LABELS = {"servicenow": "ServiceNow", "jira": "Jira", "confluence": "Confluence",
                  "kubernetes": "Kubernetes", "aws": "AWS", "bitbucket": "Bitbucket"}


def family_label(family: str) -> str:
    return _FAMILY_LABELS.get(family, family)


async def list_entities(
    db: AsyncSession, *, types: Iterable[str] | None = None, query: str = "", limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    """``{type: [items], "limit": n}`` for the requested types (default: all). Unknown types are ignored."""
    wanted = [item for item in (types or ENTITY_TYPES) if item in ENTITY_TYPES]
    needle = str(query or "").strip().lower()[:100]
    size = max(1, min(int(limit), MAX_LIMIT))
    loaders = {
        "workspaces": lambda: _workspaces(db, needle, size),
        "users": lambda: _users(db, needle, size),
        "roles": lambda: _roles(db, needle, size),
        "groups": lambda: _groups(db, needle, size),
        "named_connections": lambda: _named_connections(db, needle, size),
        "model_aliases": lambda: _model_aliases(db, needle, size),
    }
    payload: dict[str, Any] = {"limit": size}
    for name in wanted:
        if name == "tools":
            payload[name] = tool_items(needle, size)
        elif name == "connector_families":
            payload[name] = _families(needle, size)
        else:
            payload[name] = await loaders[name]()
    return payload


@dataclass(frozen=True, slots=True)
class NameIndex:
    """Names for the ids a policy stores; ``None`` for an id that does not exist (any more)."""

    workspaces: Mapping[str, str] = field(default_factory=dict)
    users: Mapping[str, str] = field(default_factory=dict)
    connections: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def workspace(self, workspace_id: str) -> str | None:
        return self.workspaces.get(workspace_id)

    def user(self, user_id: str) -> str | None:
        return self.users.get(user_id)

    def group(self, name: str) -> str:
        """Groups are stored by name; the public view (``policy_links``) hides it."""
        return name

    def connection(self, connection_id: str) -> tuple[str, str] | None:
        """``(name, connector)``; the unnamed default entry is ``("default", "")``."""
        if connection_id == DEFAULT_CONNECTION:
            return DEFAULT_CONNECTION, ""
        return self.connections.get(connection_id)


async def load_name_index(db: AsyncSession) -> NameIndex:
    workspaces = dict((await db.execute(select(Project.id, Project.name))).all())
    users = {row.id: row.display_name or row.username for row in (await db.execute(select(User))).scalars()}
    connections = {row.id: (row.name, row.tool_name)
                   for row in (await db.execute(select(ConnectorNamedConnection))).scalars()}
    return NameIndex({str(k): str(v) for k, v in workspaces.items()}, users, connections)


__all__ = [
    "DEFAULT_CONNECTION",
    "ENTITY_TYPES",
    "NameIndex",
    "family_label",
    "list_entities",
    "load_name_index",
    "tool_items",
]
