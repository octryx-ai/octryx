"""Bitbucket Cloud specifics of a run's source-control actions: where the repository's connection runs, and the
requester's Atlassian account (the pull request reviewer)."""

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
REQUESTER_IS_AUTHOR = "requester_is_author"


async def serving_config(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any], *,
                         tool_name: str = "create_bitbucket_pull_request") -> dict[str, Any]:
    base = await get_project_config(run.project_id, db) if run.project_id else {}
    return planned_tool_config(tool_name, repo_args, base, agent_tool=False)


async def is_cloud_repository(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any]) -> bool:
    config = await serving_config(db, run, repo_args)
    return str(config.get(DEPLOYMENT_FIELD) or "").strip().lower() == "cloud"


async def personal_connection(db: AsyncSession, run: WorkflowRun, repo_args: dict[str, Any], *,
                              tool_name: str = "create_bitbucket_pull_request") -> bool:
    # A connection someone else saved (an admin's bot account) is never assumed to be the requester's.
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
