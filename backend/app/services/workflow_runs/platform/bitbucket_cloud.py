"""Bitbucket Cloud specifics of a run's source-control actions: where the repository's connection runs, and the
requester's Atlassian account (the pull request reviewer).

- **deployment**: the connection that would serve the run's repository (the same route plan the tool router uses
  for ``create_bitbucket_pull_request``) names ``bitbucket_deployment``; only ``cloud`` is Bitbucket Cloud;
- **requester**: Bitbucket Cloud names reviewers by Atlassian account id and has no lookup by email. The account
  is, in this order: the requester's linked Atlassian account (``services/linked_accounts``, explicit), else the
  account of their platform email through the Workspace's Jira Cloud connection (``search_jira_users`` with
  ``email``: exactly one account whose visible email equals it, else nothing — a hidden address asks for the linked
  account). An unresolved requester never blocks the pull request (``scm.open_pr``: opened without them as reviewer,
  ``reviewer_skipped: requester_unresolved``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ConnectorNamedConnection, User, WorkflowRun
from ...linked_accounts.contract import ATLASSIAN
from ...linked_accounts.resolution import linked_identifier
from ...named_connections.service_config import planned_tool_config
from ...project.service import get_project_config
from .dispatch import dispatch_tool

DEPLOYMENT_FIELD = "bitbucket_deployment"
# ``requester_account``'s answer when the requester is the connection's own account (the pull request's author).
REQUESTER_IS_AUTHOR = "requester_is_author"


async def serving_config(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any], *,
                         tool_name: str = "create_bitbucket_pull_request") -> dict[str, Any]:
    """The non-secret config of the connection ``tool_name`` on this repository would run on ({} if refused).
    The run's own steps use it, so a connection whose agent tools are read-only still serves it (otherwise
    the repository check of a device phase found no host and refused ``run_repository_unverifiable``)."""
    base = await get_project_config(run.project_id, db) if run.project_id else {}
    return planned_tool_config(tool_name, repo_args, base, agent_tool=False)


async def is_cloud_repository(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any]) -> bool:
    config = await serving_config(db, run, repo_args)
    return str(config.get(DEPLOYMENT_FIELD) or "").strip().lower() == "cloud"


async def personal_connection(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any], *,
                              tool_name: str = "create_bitbucket_pull_request") -> bool:
    """Whether the Bitbucket Cloud account serving this repository is the requester's own: the serving config signs
    in with a username (an Atlassian account email plus that account's API token, which always belongs to the person
    whose email signs it) and every saved connection with that username and URL was saved by the requester
    (``created_by``). A connection someone else saved (an admin's bot account) is never assumed to be theirs.

    The account is matched by its username and normalized URL against saved connections, not by the route's
    target, so a passthrough route without a named target still matches."""
    if not run.requested_by:
        return False
    config = await serving_config(db, run, repo_args, tool_name=tool_name)
    username = str(config.get("bitbucket_username") or "").strip().lower()
    url = str(config.get("bitbucket_url") or "").strip().rstrip("/").lower()
    if not username:
        return False
    rows = (await db.execute(select(ConnectorNamedConnection).where(
        ConnectorNamedConnection.tool_name == "bitbucket"))).scalars().all()
    same = [row for row in rows
            if str(dict(row.config or {}).get("bitbucket_username") or "").strip().lower() == username
            and str(dict(row.config or {}).get("bitbucket_url") or "").strip().rstrip("/").lower() in ("", url)]
    return bool(same) and all(str(row.created_by or "") == str(run.requested_by) for row in same)


def _ticket_project(run: WorkflowRun) -> str:
    key = str(run.ticket_key or "").strip()
    return key.rsplit("-", 1)[0].upper() if "-" in key else ""


async def requester_account(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any] | None = None,
                            ) -> tuple[str, str]:
    """``(account id, "")`` of the requester, ``("", REQUESTER_IS_AUTHOR)`` when the connection is their own, or
    ``("", why)`` naming what to link."""
    explicit = await linked_identifier(db, run.requested_by, ATLASSIAN)
    if explicit:
        return explicit, ""
    if repo_args is not None and await personal_connection(db, run, repo_args):
        return "", REQUESTER_IS_AUTHOR
    user = await db.get(User, run.requested_by)
    email = str(getattr(user, "email", None) or "").strip()
    name = getattr(user, "username", None) or "the requester"
    remedy = ("link their Atlassian account (the account id of the Bitbucket user) in Profile → Linked accounts; "
              f"the email lookup only finds an Atlassian account whose visible email is exactly {name}'s Octryx "
              "email")
    if not email:
        return "", f"{name} has no email to find their Atlassian account by; {remedy}"
    project = _ticket_project(run)
    outcome = await dispatch_tool(db, run, "search_jira_users", {"email": email, **({"project_key": project}
                                  if project else {})}, capability_class="read_only")
    users = [item for item in (outcome.result.get("users") or []) if item.get("account_id")] if outcome.ok else []
    if len(users) != 1:
        why = outcome.reason or ("no single Atlassian account has this email" if outcome.ok else "")
        return "", (f"the Atlassian account of {name} could not be resolved through the Workspace's Jira Cloud "
                    f"connection ({why}); {remedy}")
    return str(users[0]["account_id"]), ""


__all__ = ["REQUESTER_IS_AUTHOR", "is_cloud_repository", "personal_connection", "requester_account", "serving_config"]
