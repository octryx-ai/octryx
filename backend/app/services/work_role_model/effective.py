"""The effective permission of one person in one Workspace: the union of every work role that applies to them."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IdentityGroup, UserGroup, UserIdentity
from ...models.runtime.work_role_model import (
    ANY_PROVIDER,
    DELIVERY_ALL,
    WorkRole,
    WorkRoleAssignment,
    WorkRoleFunction,
    WorkRoleFunctionLink,
    WorkspaceWorkRoleSettings,
)
from .tool_sets import entries_match


@dataclass(frozen=True)
class HeldRole:
    id: str
    key: str
    name: str
    trusted: bool
    delivery_connections: str
    connection_ids: tuple[str, ...]
    command_allow: tuple[str, ...]
    command_deny: tuple[str, ...]
    functions: tuple[str, ...]
    entries: tuple[str, ...]
    via: tuple[dict, ...] = ()


@dataclass(frozen=True)
class SubjectFacts:
    user_id: str
    group_ids: frozenset[str] = frozenset()
    sso_groups: frozenset[tuple[str, str]] = frozenset()  # (provider_id, value)
    sso_roles: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class WorkRoleGrant:
    workspace_id: str | None
    user_id: str | None
    enforced: bool = False
    platform_admin: bool = False
    roles: tuple[HeldRole, ...] = ()
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def unrestricted(self) -> bool:
        return not self.enforced or self.platform_admin

    @property
    def functions(self) -> frozenset[str]:
        return frozenset(key for role in self.roles for key in role.functions)

    @property
    def entries(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry for role in self.roles for entry in role.entries))

    @property
    def trusted(self) -> bool:
        return self.enforced and any(role.trusted for role in self.roles)

    @property
    def write_connections(self) -> frozenset[str] | None:
        if self.unrestricted or any(role.delivery_connections == DELIVERY_ALL for role in self.roles):
            return None
        return frozenset(cid for role in self.roles for cid in role.connection_ids)

    @property
    def command_allow(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p for role in self.roles for p in role.command_allow))

    @property
    def command_deny(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p for role in self.roles for p in role.command_deny))

    def has_function(self, key: str) -> bool:
        return self.unrestricted or key in self.functions

    def allows_tool(self, tool_name: str) -> bool:
        if self.unrestricted:
            return True
        if tool_name not in self._cache:
            self._cache[tool_name] = entries_match(self.entries, tool_name)
        return self._cache[tool_name]

    def allows_connection(self, connection_id: str | None) -> bool:
        allowed = self.write_connections
        return allowed is None or (connection_id is not None and connection_id in allowed)


UNRESTRICTED = WorkRoleGrant(workspace_id=None, user_id=None)


async def role_based_tools_enabled(db: AsyncSession, workspace_id: str | None) -> bool:
    if not workspace_id:
        return False
    settings = await db.get(WorkspaceWorkRoleSettings, workspace_id)
    return bool(settings and settings.role_based_tools)


def _values(raw: object) -> list[str]:
    return [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else []


async def subject_facts(db: AsyncSession, user_ids: Iterable[str]) -> dict[str, SubjectFacts]:
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    groups: dict[str, set[str]] = {uid: set() for uid in ids}
    rows = await db.execute(select(UserGroup.user_id, UserGroup.group_id).join(
        IdentityGroup, IdentityGroup.id == UserGroup.group_id).where(
        UserGroup.user_id.in_(ids), IdentityGroup.is_active.is_(True)))
    for user_id, group_id in rows.all():
        groups[user_id].add(group_id)
    sso_groups: dict[str, set[tuple[str, str]]] = {uid: set() for uid in ids}
    sso_roles: dict[str, set[tuple[str, str]]] = {uid: set() for uid in ids}
    identities = (await db.execute(select(UserIdentity).where(UserIdentity.user_id.in_(ids)))).scalars().all()
    for identity in identities:
        found_groups, found_roles = _values(identity.sso_groups_json), _values(identity.sso_roles_json)
        if identity.sso_groups_json is None and identity.sso_roles_json is None:
            # Claims not kept apart (both columns empty): the one list holds the groups and the roles claim.
            found_groups = found_roles = _values(identity.external_groups_json)
        sso_groups[identity.user_id].update((identity.provider_id, value) for value in found_groups)
        sso_roles[identity.user_id].update((identity.provider_id, value) for value in found_roles)
    return {uid: SubjectFacts(uid, frozenset(groups[uid]), frozenset(sso_groups[uid]), frozenset(sso_roles[uid]))
            for uid in ids}


def assignment_matches(assignment: WorkRoleAssignment, facts: SubjectFacts) -> bool:
    kind = assignment.subject_kind
    if kind == "user":
        return assignment.user_id == facts.user_id
    if kind == "group":
        return assignment.group_id in facts.group_ids
    claims = facts.sso_groups if kind == "sso_group" else facts.sso_roles if kind == "sso_role" else frozenset()
    value = assignment.claim_value
    if assignment.provider_key == ANY_PROVIDER:
        return any(found == value for _provider, found in claims)
    return (assignment.provider_key, value) in claims


def _via(assignment: WorkRoleAssignment) -> dict:
    if assignment.subject_kind in ("sso_group", "sso_role"):
        return {"kind": assignment.subject_kind, "value": assignment.claim_value, "assignment_id": assignment.id}
    if assignment.subject_kind == "group":
        return {"kind": "group", "group_id": assignment.group_id, "assignment_id": assignment.id}
    return {"kind": "user", "assignment_id": assignment.id}


async def _workspace_roles(db: AsyncSession, workspace_id: str) -> tuple[list[WorkRoleAssignment],
                                                                         dict[str, HeldRole]]:
    assignments = list((await db.execute(select(WorkRoleAssignment).where(
        WorkRoleAssignment.project_id == workspace_id, WorkRoleAssignment.is_active.is_(True)))).scalars().all())
    role_ids = {row.role_id for row in assignments}
    if not role_ids:
        return [], {}
    roles = (await db.execute(select(WorkRole).where(WorkRole.id.in_(role_ids), WorkRole.is_active.is_(True)))
             ).scalars().all()
    links = (await db.execute(select(WorkRoleFunctionLink.role_id, WorkRoleFunction).join(
        WorkRoleFunction, WorkRoleFunction.id == WorkRoleFunctionLink.function_id).where(
        WorkRoleFunctionLink.role_id.in_(role_ids)))).all()
    functions: dict[str, list[WorkRoleFunction]] = {}
    for role_id, function in links:
        if function.project_id in (None, workspace_id):
            functions.setdefault(role_id, []).append(function)
    held = {}
    for role in roles:
        if role.project_id not in (None, workspace_id):
            continue
        policy = dict(role.command_policy_json or {})
        own = sorted(functions.get(role.id, []), key=lambda item: item.key)
        held[role.id] = HeldRole(
            id=role.id, key=role.key, name=role.name, trusted=bool(role.trusted),
            delivery_connections=role.delivery_connections or DELIVERY_ALL,
            connection_ids=tuple(_values(role.connection_ids_json)),
            command_allow=tuple(_values(policy.get("allow"))), command_deny=tuple(_values(policy.get("deny"))),
            functions=tuple(item.key for item in own),
            entries=tuple(dict.fromkeys(entry for item in own for entry in _values(item.tools_json))))
    return assignments, held


def _held_for(facts: SubjectFacts, assignments: list[WorkRoleAssignment], roles: dict[str, HeldRole]
              ) -> tuple[HeldRole, ...]:
    via: dict[str, list[dict]] = {}
    for assignment in assignments:
        if assignment.role_id in roles and assignment_matches(assignment, facts):
            via.setdefault(assignment.role_id, []).append(_via(assignment))
    return tuple(HeldRole(**{**roles[rid].__dict__, "via": tuple(paths)})
                 for rid, paths in sorted(via.items(), key=lambda item: roles[item[0]].key))


async def held_roles_by_user(db: AsyncSession, workspace_id: str, user_ids: Iterable[str]
                             ) -> dict[str, tuple[HeldRole, ...]]:
    assignments, roles = await _workspace_roles(db, workspace_id)
    facts = await subject_facts(db, user_ids)
    return {uid: _held_for(item, assignments, roles) for uid, item in facts.items()}


async def effective_permission(db: AsyncSession, user_id: str | None, workspace_id: str | None) -> WorkRoleGrant:
    if not user_id or not workspace_id:
        return WorkRoleGrant(workspace_id=workspace_id, user_id=user_id)
    from ..admin.governance.admin_access_service import is_global_admin

    enforced = await role_based_tools_enabled(db, workspace_id)
    platform_admin = await is_global_admin(db, user_id)
    held = (await held_roles_by_user(db, workspace_id, [user_id]))[user_id]
    return WorkRoleGrant(workspace_id=workspace_id, user_id=user_id, enforced=enforced,
                         platform_admin=platform_admin, roles=held)


async def members_with(db: AsyncSession, workspace_id: str | None, *, role_key: str | None = None,
                       function_key: str | None = None, user_ids: Iterable[str]) -> tuple[str, ...]:
    if not workspace_id:
        return ()
    held = await held_roles_by_user(db, workspace_id, user_ids)
    return tuple(sorted(uid for uid, roles in held.items() if any(
        (role_key is not None and role.key == role_key) or (function_key is not None and function_key in role.functions)
        for role in roles)))


__all__ = ["UNRESTRICTED", "HeldRole", "SubjectFacts", "WorkRoleGrant", "assignment_matches", "effective_permission",
           "held_roles_by_user", "members_with", "role_based_tools_enabled", "subject_facts"]
