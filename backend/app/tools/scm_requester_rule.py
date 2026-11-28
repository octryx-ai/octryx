"""The requester-is-author rule of a pull request, the same for every SCM."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

REQUESTER_IS_AUTHOR = "requester_is_author"
# The SCM refused the requester as reviewer while the author was unknown: the requester reviews outside the SCM.
REVIEWER_REFUSED = "reviewer_refused"


async def connection_author(provider: str, lookup: Callable[[], Awaitable[str]]) -> str:
    try:
        return str(await lookup() or "").strip()
    except Exception as error:  # an optional identity read never blocks the pull request
        logger.warning("SCM author lookup failed; the author counts as unknown: provider=%s error=%s", provider,
                       type(error).__name__)
        return ""


def refused_note(description: str, mention: str) -> str:
    note = (f"Requested by {mention}; the SCM did not accept {mention} as this pull request's reviewer, so "
            f"{mention}, please review and merge it.")
    return f"{description}\n\n{note}".strip()


def _same(left: str, right: str, exact: bool) -> bool:
    left, right = str(left or "").strip(), str(right or "").strip()
    return bool(left) and (left == right if exact else left.lower() == right.lower())


def apply_requester_rule(
    reviewers: list[str], *, requester: str, author: str, description: str, mention: str, exact: bool = False,
) -> tuple[list[str], str, str]:
    if not author:
        return reviewers, description, ""
    kept = [name for name in reviewers if not _same(name, author, exact)]
    if not _same(requester, author, exact):
        return kept, description, ""
    note = (f"Requested by {mention}, who is also this pull request's author (the connection's account), so no "
            f"reviewer is set: {mention}, please review and merge it.")
    return kept, f"{description}\n\n{note}".strip(), REQUESTER_IS_AUTHOR


__all__ = ["REQUESTER_IS_AUTHOR", "REVIEWER_REFUSED", "apply_requester_rule", "connection_author", "refused_note"]
