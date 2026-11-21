"""Whose seat reviews a pull request for the bot.

The bot's runs start as the Workspace's bot user, which has no device and no subscription. A review on a seat needs a
person:

1. **broadcast** (stage (i), ``broadcast``): every Workspace member who allows it is offered the review; the first
   device that takes it reviews;
2. **the pull request's author**: the person whose linked account (Profile → Linked accounts) is the author: GitHub
   login, Bitbucket Server username, or Atlassian account id on Bitbucket Cloud. A linked account counts unverified
   too: it only chooses whose seat is offered, and the seat itself is the person's own device;
3. otherwise the company route (the existing, visible fallback of ``review.seat``).

**Review seat opt-in** per person and Workspace (``Project.config["pr_review_bot"]["review_seats"]``, no migration):
a stored choice wins; without one the seat is on for the Workspace's admins and owners and off for everyone else.
Only a member of the Workspace is ever chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ...models import Project, User, WorkflowRun
from ...models.security.linked_account import UserLinkedAccount
from .starter import CONTEXT_KEY, WORKFLOW_KEY

CONFIG_KEY = "pr_review_bot"
SEATS_KEY = "review_seats"
SOURCE_AUTHOR, SOURCE_BROADCAST = "pr_author", "broadcast"
DEFAULT_ON_ROLES = frozenset({"admin", "owner"})
# Linked-account platform per provider, and whether the author is matched by account id or by username.
_AUTHOR_ACCOUNTS = {"github": ("github", "username"), "gitlab": ("gitlab", "username"),
                    "bitbucket_cloud": ("atlassian", "account_id"), "bitbucket": ("bitbucket_server", "username")}


@dataclass(frozen=True, slots=True)
class SeatPerson:
    user: User
    source: str


# ``@octryx explain`` (``explain``): the same seats, the commenter instead of the author.
EXPLAIN_KEY = "pr-review-explain"
SOURCE_COMMENTER = "commenter"


def is_bot_run(run: WorkflowRun) -> bool:
    return run.workflow_key in (WORKFLOW_KEY, EXPLAIN_KEY)


async def _role(db: AsyncSession, user_id: str, project_id: str) -> str | None:
    from ..access_control import get_project_role_for_user

    return await get_project_role_for_user(db, user_id, project_id)


def stored_seats(project: Project | None) -> dict[str, bool]:
    section = dict((project.config or {}).get(CONFIG_KEY) or {}) if project is not None else {}
    seats = section.get(SEATS_KEY)
    return {str(key): bool(value) for key, value in seats.items()} if isinstance(seats, dict) else {}


async def review_seat_on(db: AsyncSession, project_id: str, user_id: str) -> bool:
    """The person's review seat in this Workspace: their stored choice, else on for admins and owners."""
    role = await _role(db, user_id, project_id)
    if role is None:
        return False
    stored = stored_seats(await db.get(Project, project_id))
    return stored[user_id] if user_id in stored else role in DEFAULT_ON_ROLES


async def set_review_seat(db: AsyncSession, project: Project, user_id: str, enabled: bool) -> None:
    config = dict(project.config or {})
    section = dict(config.get(CONFIG_KEY) or {})
    section[SEATS_KEY] = {**stored_seats(project), user_id: bool(enabled)}
    project.config = {**config, CONFIG_KEY: section}
    flag_modified(project, "config")


def _author_account(facts: dict[str, Any]) -> tuple[str, str, str] | None:
    """``(platform, column, value)`` of the pull request's author, or ``None`` when the event names none."""
    provider = str(facts.get("repository") or "").partition(":")[0]
    if provider == "bitbucket" and facts.get("author_id"):
        provider = "bitbucket_cloud"  # Cloud names its author by Atlassian account id; Server/DC by username
    platform, column = _AUTHOR_ACCOUNTS.get(provider, ("", ""))
    value = str(facts.get("author_id") if column == "account_id" else facts.get("author") or "").strip()
    return (platform, column, value) if platform and value else None


async def linked_users(db: AsyncSession, repository: str, author: str, author_id: str = "") -> list[User]:
    """The active people whose linked account is this SCM account (an ``@octryx`` commenter, stage D)."""
    account = _author_account({"repository": repository, "author": author, "author_id": author_id})
    if account is None:
        return []
    platform, column, value = account
    field = getattr(UserLinkedAccount, column)
    match = field == value if column == "account_id" else func.lower(field) == value.lower()
    user_ids = (await db.execute(select(UserLinkedAccount.user_id).where(
        UserLinkedAccount.platform == platform, match))).scalars().all()
    users = [await db.get(User, user_id) for user_id in dict.fromkeys(user_ids)]
    return [user for user in users if user is not None and user.is_active]


async def author_person(db: AsyncSession, run: WorkflowRun) -> User | None:
    """The Workspace member whose linked account is the pull request's author, with the review seat on."""
    if not run.project_id:
        return None
    facts = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    asked = dict(facts.get("explain") or {})
    if asked:  # an explain run: the person who asked, never the pull request's author
        facts = {**facts, "author": asked.get("author"), "author_id": asked.get("author_id")}
    for user in await linked_users(db, str(facts.get("repository") or ""), str(facts.get("author") or ""),
                                   str(facts.get("author_id") or "")):
        if await review_seat_on(db, run.project_id, user.id):
            return user
    return None


async def bot_seat_person(db: AsyncSession, run: WorkflowRun) -> SeatPerson | None:
    """The pull request author's seat (the second phase of :func:`bot_seat_phases`)."""
    user = await author_person(db, run)
    source = SOURCE_COMMENTER if run.workflow_key == EXPLAIN_KEY else SOURCE_AUTHOR
    return SeatPerson(user, source) if user is not None else None


async def broadcast_people(db: AsyncSession, run: WorkflowRun, *, besides: set[str]) -> list[User]:
    """The Workspace's members with the review seat on, but the bot user and ``besides`` (the author)."""
    from ...models.security.user import UserProject

    if not run.project_id:
        return []
    user_ids = (await db.execute(select(UserProject.user_id).where(
        UserProject.project_id == run.project_id).order_by(UserProject.user_id))).scalars().all()
    people = []
    for user_id in user_ids:
        if user_id in besides or user_id == run.requested_by:
            continue
        user = await db.get(User, user_id)
        if user is not None and user.is_active and await review_seat_on(db, run.project_id, user.id):
            people.append(user)
    return people


async def bot_seat_phases(db: AsyncSession, run: WorkflowRun) -> list[list[SeatPerson]]:
    """§12 in order: the team's seats at once (the first device that takes the offer reviews), then the author's."""
    author = await author_person(db, run)
    team = await broadcast_people(db, run, besides={author.id} if author is not None else set())
    phases = [[SeatPerson(user, SOURCE_BROADCAST) for user in team]]
    phases.append([SeatPerson(author, SOURCE_AUTHOR)] if author is not None else [])
    return [phase for phase in phases if phase]


async def seat_login(db: AsyncSession, user_id: str, repository: str) -> str:
    """How the pull request names the person: their linked login on its platform, else their name
    (not "System Administrator's seat" for an admin whose GitHub login is linked)."""
    provider = repository.partition(":")[0]
    platforms = {"github": ("github",), "gitlab": ("gitlab",),
                 "bitbucket": ("bitbucket_server", "atlassian")}.get(provider, ())
    for platform in platforms:
        row = (await db.execute(select(UserLinkedAccount).where(
            UserLinkedAccount.user_id == user_id, UserLinkedAccount.platform == platform))).scalar_one_or_none()
        if row is not None and (row.username or row.display_name):
            return str(row.username or row.display_name)
    user = await db.get(User, user_id)
    return str(user.display_name or user.username) if user is not None else ""


__all__ = ["CONFIG_KEY", "SEATS_KEY", "SOURCE_AUTHOR", "SOURCE_BROADCAST", "SeatPerson", "author_person",
           "bot_seat_person", "bot_seat_phases", "broadcast_people", "is_bot_run", "linked_users", "review_seat_on",
           "seat_login", "set_review_seat", "stored_seats"]
