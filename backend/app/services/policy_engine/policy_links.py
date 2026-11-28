"""Where policies show up outside the Policies page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .builder_model import PolicyModel
from .builder_parse import parse_est
from .entity_listing import NameIndex, load_name_index
from .policy_text import Statement
from .policy_view import CHANGE_REMOVED, describe, index
from .runtime import published_version

PUBLIC_FIELDS = ("id", "name", "description", "source", "sentence", "scope", "groups")
OTHER_WORKSPACE = "another Workspace"
HIDDEN_NAME = "(hidden)"


@dataclass(frozen=True, slots=True)
class MemberNames(NameIndex):
    own_workspace: str = ""

    def workspace(self, workspace_id: str) -> str | None:
        return NameIndex.workspace(self, workspace_id) if workspace_id == self.own_workspace else OTHER_WORKSPACE

    def user(self, user_id: str) -> str | None:
        return HIDDEN_NAME

    def group(self, name: str) -> str:
        return HIDDEN_NAME


def member_names(names: NameIndex, workspace_id: str) -> MemberNames:
    return MemberNames(names.workspaces, names.users, names.connections, own_workspace=workspace_id)


def model_applies(model: PolicyModel, workspace_id: str, classification: str | None) -> bool:
    where = model.where
    levels = catalog.classification_levels()
    if where.workspaces and workspace_id not in where.workspaces:
        return False
    if where.unclassified and classification:
        return False
    if where.classification_is and classification not in where.classification_is:
        return False
    return not (where.classification_at_least and (
        not classification or levels.index(classification) < levels.index(where.classification_at_least)))


def _applies(statement: Statement, model: PolicyModel | None, workspace_id: str, classification: str | None) -> bool:
    if model is not None:
        return model_applies(model, workspace_id, classification)
    named = statement.references.of("Workspace")
    return not named or workspace_id in named


async def workspace_platform_policies(
    db: AsyncSession, workspace_id: str, classification: str | None
) -> dict[str, Any]:
    published = await published_version(db)
    if published is None:
        return {"version": None, "items": []}
    names = member_names(await load_name_index(db), workspace_id)
    items = []
    for statement in index(published.policies_text):
        model = parse_est(statement.est, statement.text)
        if not _applies(statement, model, workspace_id, classification):
            continue
        item = describe(statement, names)
        public = {key: item[key] for key in PUBLIC_FIELDS}
        public["conditional"] = model is None and statement.has_conditions
        items.append(public)
    return {"version": published.version, "items": items}


def _connector_of(names: NameIndex, connection_id: str) -> str | None:
    found = names.connection(connection_id)
    return found[1] if found and found[1] else None


def reference_counts(items: list[dict[str, Any]], names: NameIndex) -> dict[str, Any]:
    connectors: dict[str, list[dict[str, str]]] = {}
    connector_wide: dict[str, list[dict[str, str]]] = {}
    connections: dict[str, list[dict[str, str]]] = {}
    for item in items:
        if item.get("change") == CHANGE_REMOVED:
            continue
        entry = {"id": item["id"], "name": item["name"]}
        refs = item["references"]
        families = set(refs["entities"].get("ConnectorFamily", []))
        named = list(refs["connections"])
        touched = families | {connector for connector in (_connector_of(names, value) for value in named) if connector}
        for connector in sorted(touched):
            connectors.setdefault(connector, []).append(entry)
        if not named:
            for family in sorted(families):
                connector_wide.setdefault(family, []).append(entry)
        for connection in named:
            connections.setdefault(connection, []).append(entry)

    def counted(groups: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
        return {key: {"count": len(value), "policies": value} for key, value in sorted(groups.items())}

    return {"connectors": counted(connectors), "connector_wide": counted(connector_wide),
            "connections": counted(connections)}


async def working_reference_counts(db: AsyncSession) -> dict[str, Any]:
    from .policy_view import policies_view, working_version

    view = await policies_view(db, await working_version(db))
    return reference_counts(view["items"], await load_name_index(db))


__all__ = [
    "MemberNames",
    "member_names",
    "model_applies",
    "reference_counts",
    "workspace_platform_policies",
    "working_reference_counts",
]
