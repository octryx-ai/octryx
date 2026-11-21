"""What differs per platform for the review bot, as data: its governed tools, how they name a pull request, and how
the platform names a person. Every bot module reads these tables instead of its own ``if provider == ...``.

GitLab calls a pull request a merge request and names it by its ``iid`` (the number in its URL); its people are
mentioned with ``@username`` like on GitHub, and a member's access level is cheap to read (``permissions_for``).
Bitbucket names people by display name or username and does not let the bot read their repository permission.
"""

from __future__ import annotations

LIST_TOOLS = {"github": "list_github_pull_request_heads", "gitlab": "list_gitlab_merge_request_heads",
              "bitbucket": "list_bitbucket_pull_request_heads"}
POST_TOOLS = {"github": "post_github_pull_request_review", "gitlab": "post_gitlab_merge_request_review",
              "bitbucket": "post_bitbucket_pull_request_review"}
#: The post tool's argument that names the pull request.
PR_KEYS = {"github": "pr_number", "gitlab": "mr_iid", "bitbucket": "pr_id"}
#: Platforms where ``@login`` mentions the person (Bitbucket shows the name as it is).
MENTION_PROVIDERS = frozenset({"github", "gitlab"})
#: Platforms where the commenter's repository permission is read (``permissions_for``); elsewhere it is ``unknown``.
PERMISSION_PROVIDERS = frozenset({"github", "gitlab"})


def pr_key(provider: str) -> str:
    return PR_KEYS.get(provider, "pr_id")


def mention(provider: str, author: str) -> str:
    return f"@{author}" if provider in MENTION_PROVIDERS else str(author)


__all__ = ["LIST_TOOLS", "MENTION_PROVIDERS", "PERMISSION_PROVIDERS", "POST_TOOLS", "PR_KEYS", "mention", "pr_key"]
