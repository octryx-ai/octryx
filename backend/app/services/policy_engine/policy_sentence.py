"""Plain-language lines for policies: the list's "Who · What · Where", scope and warnings."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .catalog import action_info, carries_classification, carries_user
from .entity_listing import NameIndex
from .policy_text import Statement
from .schema import ID_CLASSIFICATION, ID_PLATFORM, ID_WORKSPACE

Segment = dict[str, Any]

WARN_WHO_NOT_EFFECTIVE = "who_not_effective"
WARN_CLASSIFICATION_NOT_EFFECTIVE = "classification_not_effective"
WARN_CONNECTION_UNKNOWN = "connection_unknown"
WARN_WORKSPACE_UNKNOWN = "workspace_unknown"


def text(value: str) -> Segment:
    return {"text": value, "emphasis": None}


def value(value: str) -> Segment:
    return {"text": value, "emphasis": "value"}


def verb(value: str) -> Segment:
    return {"text": value, "emphasis": "verb"}


def joined(values: Iterable[str], last: str = "or") -> str:
    items = list(dict.fromkeys(str(item) for item in values))
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def plain(segments: Iterable[Segment]) -> str:
    return "".join(segment["text"] for segment in segments)


def workspace_label(names: NameIndex, workspace_id: str) -> str:
    return names.workspace(workspace_id) or f"unknown Workspace {workspace_id}"


def connection_label(names: NameIndex, connection_id: str) -> str:
    found = names.connection(connection_id)
    return found[0] if found else f"unknown connection {connection_id}"


def _who(statement: Statement, names: NameIndex) -> list[Segment]:
    scope = statement.est.get("principal") or {}
    entity = scope.get("entity") if isinstance(scope.get("entity"), dict) else None
    if scope.get("op") in ("in", "==") and entity:
        kind, ident = entity.get("type"), str(entity.get("id"))
        if kind == "Role":
            return [text("members of role "), value(ident)]
        if kind == "Group":
            return [text("members of group "), value(names.group(ident))]
        if kind == "User":
            return [text("user "), value(names.user(ident) or f"unknown user {ident}")]
        return [value(f"{kind} {ident}")]
    if scope.get("op") == "is":
        return [text("every "), value(str(scope.get("entity_type")))]
    return [value("everyone")]


def _action_verbs(actions: Iterable[str]) -> list[str]:
    verbs = []
    for action in actions:
        try:
            verbs.append(action_info(action)["verb"])
        except KeyError:
            verbs.append(action)
    return list(dict.fromkeys(verbs))


def outline(statement: Statement, names: NameIndex) -> list[Segment]:
    effect = "Block" if statement.effect == "forbid" else "Allow"
    segments = [verb(effect), text(" ")] + _who(statement, names)
    segments += [text(" from " if effect == "Block" else " "), value(joined(_action_verbs(statement.actions), "and"))]
    connections = statement.references.connections
    if connections:
        segments += [text(" on connection "), value(joined(connection_label(names, item) for item in connections))]
    workspaces = statement.references.of("Workspace")
    if workspaces:
        segments += [text(" in "), value(joined(workspace_label(names, item) for item in workspaces))]
    if statement.has_conditions:
        segments.append(text(" (with conditions written in Cedar)"))
    segments.append(text("."))
    return segments


def scope_label(statement: Statement, names: NameIndex) -> str:
    policy_id = statement.policy_id
    if policy_id.startswith(ID_PLATFORM):
        return "Instance"
    if policy_id.startswith(ID_CLASSIFICATION):
        return f"Classification = {policy_id[len(ID_CLASSIFICATION):].split(':', 1)[0]}"
    if policy_id.startswith(ID_WORKSPACE):
        return workspace_label(names, policy_id[len(ID_WORKSPACE):].split(":", 1)[0])
    connections = statement.references.connections
    if connections:
        return "Connection " + joined(connection_label(names, item) for item in connections)
    workspaces = statement.references.of("Workspace")
    if len(workspaces) == 1:
        return workspace_label(names, workspaces[0])
    if workspaces:
        return f"{len(workspaces)} Workspaces"
    return "All Workspaces"


def _uses_classification(statement: Statement) -> bool:
    return '"attr": "classification' in json.dumps(statement.est.get("conditions") or [])


def warnings(statement: Statement, names: NameIndex) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    blind = [action for action in statement.actions if _known(action) and not carries_user(action)]
    if statement.references.uses_principal and blind:
        found.append({"code": WARN_WHO_NOT_EFFECTIVE, "actions": blind,
                      "message": "Who-conditions are not effective yet for "
                                 f"{joined(action_info(item)['label'] for item in blind)}: that check does not carry "
                                 "the user."})
    unclassified = [action for action in statement.actions if _known(action) and not carries_classification(action)]
    if _uses_classification(statement) and unclassified:
        found.append({"code": WARN_CLASSIFICATION_NOT_EFFECTIVE, "actions": unclassified,
                      "message": "Classification conditions never match for "
                                 f"{joined(action_info(item)['label'] for item in unclassified)}: that check does "
                                 "not know the Workspace classification."})
    for connection_id in statement.references.connections:
        if names.connection(connection_id) is None:
            found.append({"code": WARN_CONNECTION_UNKNOWN, "id": connection_id,
                          "message": f"References a named connection that no longer exists ({connection_id}); "
                                     "the condition never matches it."})
    for workspace_id in statement.references.of("Workspace"):
        if names.workspace(workspace_id) is None:
            found.append({"code": WARN_WORKSPACE_UNKNOWN, "id": workspace_id,
                          "message": f"References a Workspace that no longer exists ({workspace_id})."})
    return found


def _known(action: str) -> bool:
    try:
        action_info(action)
    except KeyError:
        return False
    return True


__all__ = [
    "WARN_CLASSIFICATION_NOT_EFFECTIVE",
    "WARN_CONNECTION_UNKNOWN",
    "WARN_WHO_NOT_EFFECTIVE",
    "WARN_WORKSPACE_UNKNOWN",
    "Segment",
    "connection_label",
    "joined",
    "outline",
    "plain",
    "scope_label",
    "text",
    "value",
    "verb",
    "warnings",
    "workspace_label",
]
