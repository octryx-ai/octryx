"""Who a run's pull request asks to review it, and what happens when the requester cannot be one.

- **requester**: their account on the run's SCM, read only from their linked accounts (``services/linked_accounts``:
  GitHub login, GitLab username, Bitbucket Server username; on Bitbucket Cloud their Atlassian account, else the
  exact-email lookup, ``bitbucket_cloud.requester_account``);
- **requester is the connection's account** (Bitbucket Cloud: they saved the serving connection with their own
  Atlassian API token): no reviewer is set for them (Bitbucket refuses an author as reviewer), the description
  mentions them and the run records ``reviewer_skipped: requester_is_author`` - never ``requester_unresolved``;
- **unresolved requester** (no linked account, or the SCM does not know it): the pull request is still opened, without
  them as reviewer; the description mentions them by their platform name, the run records ``reviewer_skipped:
  requester_unresolved`` (run event, run card, Inbox: "link your account to be added as reviewer"). The watched merge
  is unchanged. A retried step after linking resolves them again: they become the reviewer, or the
  requester-is-author exception applies (``tools/scm_requester_rule.py``).
- **stand-in** (``pr_reviewers.json`` ``fallback_roles``): for an unresolved requester, the first Workspace member of
  those roles with a linked account on that SCM is asked to review instead, and the description says so; with none,
  the unresolved note above stays the one sentence (a run started over the API may have nobody
  to ask).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, UserProject, WorkflowRun
from ...linked_accounts.contract import PLATFORMS
from ...linked_accounts.resolution import linked_identifier, scm_platform
from ..records import record_event
from . import bitbucket_cloud

REQUESTER_UNRESOLVED = "requester_unresolved"
REQUESTER_IS_AUTHOR = bitbucket_cloud.REQUESTER_IS_AUTHOR


@dataclass(frozen=True, slots=True)
class PrReviewers:
    """The requester's SCM identity (``""`` when unresolved, with ``unresolved`` saying why) and the owners."""

    requester: str
    owners: tuple[str, ...]
    platform: str
    unresolved: str = ""
    is_author: bool = False  # the requester is the connection's account: no reviewer, ``requester_is_author``

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys([*([self.requester] if self.requester else []), *self.owners]))


async def requester_reviewer(db: AsyncSession, run: WorkflowRun, ref) -> tuple[str, str, str]:
    """``(identity, linked-account platform, why unresolved)`` of the requester on the run's SCM."""
    cloud = ref.provider == "bitbucket" and await bitbucket_cloud.is_cloud_repository(db, run, ref.args())
    platform_key = scm_platform(ref.provider, cloud=cloud)
    if cloud:
        account, missing = await bitbucket_cloud.requester_account(db, run, ref.args())
        return account, platform_key, missing
    identity = await linked_identifier(db, run.requested_by, platform_key)
    if identity:
        return identity, platform_key, ""
    user = await db.get(User, run.requested_by)
    label = PLATFORMS[platform_key].label if platform_key in PLATFORMS else ref.provider
    return "", platform_key, (f"{getattr(user, 'username', None) or 'the requester'} has no linked {label} account "
                              "(Profile → Linked accounts)")


def _fallback_roles() -> list[str]:
    data = json.loads(Path(__file__).with_name("pr_reviewers.json").read_text(encoding="utf-8"))
    return [str(role) for role in data.get("fallback_roles") or []]


async def stand_in(db: AsyncSession, run: WorkflowRun, platform_key: str) -> tuple[str, str]:
    """``(SCM identity, display name)`` of the Workspace member who reviews for an unresolved requester; ``("", "")``
    when the rule names nobody with a linked account."""
    for role in _fallback_roles():
        rows = (await db.execute(select(UserProject.user_id).where(
            UserProject.project_id == run.project_id, UserProject.role == role,
            UserProject.user_id != run.requested_by).order_by(UserProject.granted_at))).scalars().all()
        for user_id in rows:
            identity = await linked_identifier(db, user_id, platform_key)
            user = await db.get(User, user_id) if identity else None
            if identity and user is not None and getattr(user, "is_active", True):
                return identity, str(user.display_name or user.username or identity)
    return "", ""


def stand_in_note(description: str, mention: str, platform_key: str, name: str) -> str:
    label = PLATFORMS[platform_key].label if platform_key in PLATFORMS else "SCM"
    note = (f"Requested by {mention} (Octryx), whose {label} account is not linked, so {name} (a Workspace "
            "owner or admin, by the Octryx reviewer rule) is asked to review it instead.")
    return f"{description}\n\n{note}".strip()


async def requester_mention(db: AsyncSession, run: WorkflowRun) -> str:
    user = await db.get(User, run.requested_by)
    return str(getattr(user, "display_name", None) or getattr(user, "username", None) or "the requester")


def unresolved_note(description: str, mention: str, platform_key: str) -> str:
    label = PLATFORMS[platform_key].label if platform_key in PLATFORMS else "SCM"
    note = (f"Requested by {mention} (Octryx). Their {label} account is not linked, so they are not this pull "
            f"request's reviewer: {mention}, please review and merge it.")
    return f"{description}\n\n{note}".strip()


def author_note(description: str, mention: str) -> str:
    note = (f"Requested by {mention} (Octryx), who is also this pull request's author (the connection signs in with "
            f"their account), so no reviewer is set: {mention}, please review and merge it.")
    return f"{description}\n\n{note}".strip()


def record_reviewer_skipped(db: AsyncSession, run: WorkflowRun, reason: str, *, detail: str = "") -> None:
    """The requester reviews their own pull request outside the SCM: recorded on the run and as a run event."""
    run.context = {**dict(run.context or {}), "reviewer_skipped": reason}
    record_event(db, run, "reviewer_skipped", detail={"reason": reason, "pull_request": dict(run.pull_request or {}),
                                                      **({"why": detail} if detail else {})})


__all__ = ["REQUESTER_IS_AUTHOR", "REQUESTER_UNRESOLVED", "PrReviewers", "author_note", "record_reviewer_skipped",
           "requester_mention", "requester_reviewer", "stand_in", "stand_in_note", "unresolved_note"]
