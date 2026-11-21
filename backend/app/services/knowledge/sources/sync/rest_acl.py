"""Who may read a Custom REST record in Knowledge: the Octryx roles whose grants would return it.

The API is reached with a technical account, so the source system has no ACL to mirror: Octryx's grants *are* the
ACL (``rest_connector/authorization``). Knowledge must not widen them: a person who could not read a
record through the ``rest__`` tool must not find it in a knowledge search either.

**Facet.** A record listed as the acting role (its scope parameters injected, its result filter applied) is admitted
to every role holding a grant of this Workspace (or of every Workspace) on the list operation that sees *at least*
what the acting role saw for this record:

- the grant is unscoped, or every scope parameter it fixes is fixed to the same value for the acting role (fewer
  fixed parameters only widen a listing), and
- it has no result filter, or its filter admits this record.

With a detail operation the same rule applies to the detail operation's grants (without a record: a filter must be
the acting one's), and only roles admitted by both are kept: the knowledge holds the detail content too. The facet is
``restricted`` with mechanism ``octryx_grant`` and principals ``role:<key>``; more than 20 roles is incomplete, which
the runner withholds as ``acl_unresolved``.

**Expansion.** The roles become the addresses of the Workspace's current human members (direct or through an active
group) who hold one of them: a platform role (as the chat's tool context reads it, ``viewer`` when none), or a work
role key (``work_role_model.effective.held_roles_by_user``, SSO groups and claims included). The address is the
platform account's own, which is exactly what a reader's principal key is derived from
(``access/acl_keys.reader_principal_keys``); an address that is not one is counted ``unmapped``. Expansions are
cached per run by role set: many records share one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models import Role, UserRole
from ....rest_connector.authorization import AppliedScope, Grant, grants_of
from ....rest_connector.response import get_path
from ...access.acl_keys import normalize_email
from .contract import AclExpansion, AclFacet

MECHANISM = "octryx_grant"
PRINCIPAL_PREFIX = "role:"
# The chat's tool context gives a person without any platform role this one (``agent/core/context/run_context``).
DEFAULT_PLATFORM_ROLE = "viewer"


def _filter_admits(grant: Grant, applied: AppliedScope, record: Mapping[str, Any] | None) -> bool:
    wanted = grant.result_filter
    if wanted is None or wanted == applied.result_filter:
        return True
    if record is None:
        return False
    actual = get_path(record, str(wanted.get("field") or ""))  # a missing path is no scalar: not admitted
    return isinstance(actual, str | int | float | bool) and (
        actual == wanted.get("value") or str(actual) == str(wanted.get("value")))


def _sees_at_least(grant: Grant, applied: AppliedScope, record: Mapping[str, Any] | None) -> bool:
    if not grant.scoped:
        return True
    fixed = applied.params
    return all(name in fixed and fixed[name] == value for name, value in grant.scope.items()) \
        and _filter_admits(grant, applied, record)


def admitted_roles(operation: Any, applied: AppliedScope, project_id: str,
                   record: Mapping[str, Any] | None) -> frozenset[str]:
    """The lower-case roles whose grants of ``operation`` see at least what ``applied`` saw (of ``record``)."""
    return frozenset(grant.role.lower() for grant in grants_of(operation)
                     if grant.workspace_id in (None, project_id) and _sees_at_least(grant, applied, record))


def facet_for(roles: Iterable[str]) -> AclFacet:
    return AclFacet.restricted(MECHANISM, tuple(f"{PRINCIPAL_PREFIX}{role}" for role in sorted(set(roles))))


def roles_of(facet: AclFacet) -> frozenset[str] | None:
    """The roles a facet of this connector names; ``None`` for any other mechanism."""
    if facet.restriction != MECHANISM:
        return None
    return frozenset(item[len(PRINCIPAL_PREFIX):] for item in facet.principals if item.startswith(PRINCIPAL_PREFIX))


async def _platform_roles(db: AsyncSession, user_ids: list[str]) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = {user_id: set() for user_id in user_ids}
    rows = await db.execute(select(UserRole.user_id, Role.name).join(Role, Role.id == UserRole.role_id)
                            .where(UserRole.user_id.in_(user_ids)))
    for user_id, name in rows.all():
        roles[user_id].add(str(name).lower())
    return {user_id: found or {DEFAULT_PLATFORM_ROLE} for user_id, found in roles.items()}


async def roles_of_user(db: AsyncSession, project_id: str, user_id: str) -> frozenset[str]:
    """One person's platform roles and work role keys in the Workspace (lower case), as the expansion reads them."""
    from ....work_role_model.effective import held_roles_by_user

    held = (await held_roles_by_user(db, project_id, [user_id])).get(user_id, ())
    return frozenset((await _platform_roles(db, [user_id]))[user_id] | {role.key.lower() for role in held})


async def expand_roles(db: AsyncSession, project_id: str, roles: frozenset[str]) -> AclExpansion:
    """The addresses of the Workspace's human members holding one of ``roles``; never anyone outside it."""
    from ....work_role_model.effective import held_roles_by_user
    from ....workflow_runs.work_roles import workspace_humans

    members = await workspace_humans(db, project_id)
    if not members or not roles:
        return AclExpansion(member_emails=(), unmapped=0)
    ids = sorted(members)
    platform = await _platform_roles(db, ids)
    held = await held_roles_by_user(db, project_id, ids)
    emails: set[str] = set()
    unmapped = 0
    for user_id in ids:
        holds = platform[user_id] | {role.key.lower() for role in held.get(user_id, ())}
        if not holds & roles:
            continue
        email = normalize_email(members[user_id].email)
        if email is None:
            unmapped += 1
        else:
            emails.add(email)
    return AclExpansion(member_emails=tuple(sorted(emails)), unmapped=unmapped)


__all__ = ["MECHANISM", "admitted_roles", "expand_roles", "facet_for", "roles_of", "roles_of_user"]
