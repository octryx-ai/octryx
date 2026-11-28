"""What reviewer, author and assignee resolution reads: a user's linked accounts, nothing else."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UserLinkedAccount
from .contract import ATLASSIAN, BITBUCKET_SERVER, GITHUB, GITLAB, PLATFORMS
from .store import account_row, identifier_of

_SCM_PLATFORMS = {"github": GITHUB, "gitlab": GITLAB, "bitbucket": BITBUCKET_SERVER}


def scm_platform(provider: str, *, cloud: bool = False) -> str:
    if provider == "bitbucket" and cloud:
        return ATLASSIAN
    return _SCM_PLATFORMS.get(provider, "")


async def linked_identifier(db: AsyncSession, user_id: str | None, platform_key: str) -> str:
    if not user_id or platform_key not in PLATFORMS:
        return ""
    return identifier_of(await account_row(db, user_id, platform_key))


async def account_identifiers(db: AsyncSession, user_id: str) -> set[str]:
    return (await account_names(db, {user_id})).get(user_id, set())


async def account_names(db: AsyncSession, user_ids: set[str]) -> dict[str, set[str]]:
    if not user_ids:
        return {}
    names: dict[str, set[str]] = defaultdict(set)
    for row in (await db.execute(select(UserLinkedAccount).where(UserLinkedAccount.user_id.in_(user_ids)))).scalars():
        if row.platform in PLATFORMS and identifier_of(row):
            names[row.user_id].add(identifier_of(row).lower())
    return names


async def users_by_account_name(db: AsyncSession, names: set[str]) -> dict[str, set[str]]:
    if not names:
        return {}
    rows = (await db.execute(select(UserLinkedAccount).where(or_(
        func.lower(UserLinkedAccount.account_id).in_(names), func.lower(UserLinkedAccount.username).in_(names),
    )))).scalars().all()
    named: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.platform in PLATFORMS and identifier_of(row).lower() in names:
            named[identifier_of(row).lower()].add(row.user_id)
    return named


__all__ = ["account_identifiers", "account_names", "linked_identifier", "scm_platform", "users_by_account_name"]
