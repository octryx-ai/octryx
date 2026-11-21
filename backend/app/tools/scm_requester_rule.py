"""The requester-is-author rule of a pull request, the same for every SCM.

The run's requester reviews the pull request. When the connection signs in as the requester — the pull request's
author — no SCM lets them review it (Bitbucket and GitHub refuse it; GitLab is held to the same rule). Then the PR tool
sets no reviewer for them, mentions them in the description instead and answers ``reviewer_skipped:
requester_is_author``; the workflow records it and notifies the requester (run card, Inbox). The watched merge is
unchanged. With a separate (bot) account on the connection the requester is a reviewer, without any switch.

Any other reviewer that is the author is dropped too (the SCM would refuse the whole request); only the requester
decides the skip.

Who the connection's account is, is a **best-effort** lookup (:func:`connection_author`): a token that may not read
its own account (a GitHub App or fine-grained token, a Bitbucket token without ``read:user``, an SCM without that
endpoint) never blocks the pull request. The author then counts as unknown, the requester is requested as reviewer
(the default), and when the SCM refuses that reviewer the pull request is still opened (or kept) without them and the
answer says ``reviewer_skipped: reviewer_refused`` — the run notifies the requester exactly as for the author case.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

REQUESTER_IS_AUTHOR = "requester_is_author"
# The SCM refused the requester as reviewer while the author was unknown: the requester reviews outside the SCM.
REVIEWER_REFUSED = "reviewer_refused"


async def connection_author(provider: str, lookup: Callable[[], Awaitable[str]]) -> str:
    """The connection's account (login / username / account id), or ``""`` when the SCM does not tell."""
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
    """``(reviewers to request, description, reviewer_skipped)``; unchanged unless the requester is the author."""
    if not author:
        return reviewers, description, ""
    kept = [name for name in reviewers if not _same(name, author, exact)]
    if not _same(requester, author, exact):
        return kept, description, ""
    note = (f"Requested by {mention}, who is also this pull request's author (the connection's account), so no "
            f"reviewer is set: {mention}, please review and merge it.")
    return kept, f"{description}\n\n{note}".strip(), REQUESTER_IS_AUTHOR


__all__ = ["REQUESTER_IS_AUTHOR", "REVIEWER_REFUSED", "apply_requester_rule", "connection_author", "refused_note"]
