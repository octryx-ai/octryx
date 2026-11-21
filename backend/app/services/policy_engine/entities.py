"""Cedar entities built from the facts an enforcement point already holds.

The enforcement point is the policy information point: it resolves the Workspace classification, the tool's
connector family, the command segments and so on exactly as the existing decision does, and hands Cedar those
facts as entity attributes. Cedar never re-derives them (it cannot parse a shell command or read tool metadata).

Command facts mirror ``agent_gateway/command_match`` so that a translated tool rule matches exactly when the
structural matcher does: ``prefixes`` stop at the first token that is empty or contains whitespace (a rule
token never does, so no longer prefix could equal a rule), and ``arguments`` holds every token after the program
plus the name of every ``name=value`` token (``segment_has_argument``'s ``argument=`` form).
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.services.agent_gateway.policy_keys import MAX_TOKENS

from .engine import EntityRef
from .schema import (
    ENTITY_AGENT_SESSION,
    ENTITY_COMMAND,
    ENTITY_CONNECTOR_FAMILY,
    ENTITY_DEVICE,
    ENTITY_GROUP,
    ENTITY_MODEL_ALIAS,
    ENTITY_PATH,
    ENTITY_REMOTE_MODEL,
    ENTITY_ROLE,
    ENTITY_TOOL,
    ENTITY_USER,
    ENTITY_WORKSPACE,
    UNKNOWN_ID,
)

MAX_LINE_CHARS = 4000


def _record(ref: EntityRef, attrs: Mapping[str, Any], parents: Iterable[EntityRef] = ()) -> dict[str, Any]:
    return {"uid": ref.to_json(), "attrs": dict(attrs), "parents": [parent.to_json() for parent in parents]}


def principal_entities(
    user_id: str | None,
    *,
    roles: Iterable[str] = (),
    groups: Iterable[str] = (),
    platform_admin: bool = False,
    session_id: str | None = None,
    profile: str = "",
    client: str = "",
    sensitive: Iterable[str] = (),
) -> tuple[EntityRef, list[dict[str, Any]]]:
    """The principal (the AgentSession when ``session_id`` is given, else the User) and its entities.

    ``sensitive``: the content categories the conversation already contained; a principal loaded once per
    request carries none, and the content points set them per conversation (:func:`with_sensitive`).
    """
    user = EntityRef(ENTITY_USER, str(user_id or "").strip() or UNKNOWN_ID)
    parents = [EntityRef(ENTITY_ROLE, role) for role in sorted(set(roles))]
    parents += [EntityRef(ENTITY_GROUP, group) for group in sorted(set(groups))]
    records = [_record(user, {"platform_admin": bool(platform_admin)}, parents)]
    if not session_id:
        return user, records
    session = EntityRef(ENTITY_AGENT_SESSION, session_id)
    records.append(_record(session, {"profile": profile, "client": client, "sensitive": sorted(set(sensitive))},
                           [user]))
    return session, records


def with_sensitive(
    principal: EntityRef, records: Sequence[Mapping[str, Any]], categories: Iterable[str]
) -> list[Mapping[str, Any]]:
    """``records`` with the AgentSession principal's ``sensitive`` set to ``categories`` (a User is unchanged)."""
    if principal.type != ENTITY_AGENT_SESSION:
        return list(records)
    wanted = sorted(set(categories))
    return [{**record, "attrs": {**record["attrs"], "sensitive": wanted}} if record.get("uid") == principal.to_json()
            else record for record in records]


def workspace_entity(
    workspace_id: str | None,
    *,
    classification: str | None = None,
    classification_rank: int | None = None,
    seat_mode: str = "forbidden",
    requires_governed_routing: bool = False,
) -> tuple[EntityRef, dict[str, Any]]:
    ref = EntityRef(ENTITY_WORKSPACE, str(workspace_id or "").strip() or UNKNOWN_ID)
    attrs: dict[str, Any] = {"seat_mode": seat_mode, "requires_governed_routing": bool(requires_governed_routing)}
    if classification:
        attrs["classification"] = classification
    if classification_rank is not None:
        attrs["classification_rank"] = classification_rank
    return ref, _record(ref, attrs)


def device_entity(device_id: str, *, owner_user_id: str, os: str, profiles: Iterable[str],
                  status: str) -> tuple[EntityRef, dict[str, Any]]:
    """A user's device, child of its owner."""
    ref = EntityRef(ENTITY_DEVICE, str(device_id or "").strip() or UNKNOWN_ID)
    attrs = {"os": str(os or ""), "profiles": sorted(set(profiles)), "status": str(status or "")}
    return ref, _record(ref, attrs, [EntityRef(ENTITY_USER, str(owner_user_id or "").strip() or UNKNOWN_ID)])


def tool_entity(name: str, family: str | None) -> tuple[EntityRef, dict[str, Any]]:
    ref = EntityRef(ENTITY_TOOL, name)
    parents = [EntityRef(ENTITY_CONNECTOR_FAMILY, family)] if family else []
    return ref, _record(ref, {"name": name}, parents)


def model_alias_entity(alias: str, approved_for: Iterable[str] = ()) -> tuple[EntityRef, dict[str, Any]]:
    """``approved_for``: the alias catalog's ``approved_data_categories``; a seat model has none."""
    ref = EntityRef(ENTITY_MODEL_ALIAS, alias)
    return ref, _record(ref, {"alias": alias, "approved_for": sorted(set(approved_for))})


def remote_model_entity(kind: str, data_policy_class: str, rank: int | None) -> tuple[EntityRef, dict[str, Any]]:
    ref = EntityRef(ENTITY_REMOTE_MODEL, f"{kind}:{data_policy_class or UNKNOWN_ID}")
    attrs: dict[str, Any] = {"kind": kind}
    if rank is not None:
        attrs["data_policy_class"] = data_policy_class
        attrs["data_policy_rank"] = rank
    return ref, _record(ref, attrs)


def _plain(token: str) -> bool:
    return bool(token) and not any(char.isspace() for char in token)


def command_facts(segment: Sequence[str]) -> dict[str, Any]:
    program = posixpath.basename(segment[0]) if segment else ""
    prefixes: list[str] = []
    words = [program, *segment[1:MAX_TOKENS]]
    for size in range(1, len(words) + 1):
        if not _plain(words[size - 1]):
            break
        prefixes.append(" ".join(words[:size]))
    arguments: set[str] = set()
    values: set[str] = set()
    tail = list(segment[1:])
    for index, token in enumerate(tail):
        arguments.add(token)
        arguments.update(token[:position] for position, char in enumerate(token) if char == "=")
        if token.startswith("-") and "=" in token:
            values.add(token)
        elif token.startswith("-") and index + 1 < len(tail) and not tail[index + 1].startswith("-"):
            values.add(f"{token}={tail[index + 1]}")
    return {
        "line": " ".join(segment)[:MAX_LINE_CHARS],
        "program": program,
        "parseable": True,
        "prefixes": prefixes,
        "arguments": sorted(arguments),
        "argument_values": sorted(values),
    }


def command_entity(uid: str, segment: Sequence[str] | None, raw: str = "") -> tuple[EntityRef, dict[str, Any]]:
    """One segment's Command, or (``segment`` ``None``) the unparseable command as a whole."""
    ref = EntityRef(ENTITY_COMMAND, uid)
    if segment is None:
        attrs = {"line": str(raw)[:MAX_LINE_CHARS], "program": "", "parseable": False, "prefixes": [],
                 "arguments": [], "argument_values": []}
    else:
        attrs = command_facts(segment)
    return ref, _record(ref, attrs)


def path_entity(uid: str, path: str) -> tuple[EntityRef, dict[str, Any]]:
    ref = EntityRef(ENTITY_PATH, uid)
    return ref, _record(ref, {"path": path})


__all__ = [
    "command_entity",
    "command_facts",
    "device_entity",
    "model_alias_entity",
    "path_entity",
    "principal_entities",
    "remote_model_entity",
    "tool_entity",
    "with_sensitive",
    "workspace_entity",
]
