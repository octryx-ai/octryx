"""The Workspace's Jira allowlist applied to the Secure Work intake.

The Jira intake (dry-run, sync and scheduled runs) reads exactly what the agent tools and the
Knowledge connector of the same Workspace may read: the effective connection's
``jira_allowed_projects`` (``tools/jira_impl/_jira_helpers_context.py`` semantics: unset or empty is
unrestricted, otherwise the upper-cased project keys).

- An intake whose ``project_keys`` filter names a project outside the allowlist is refused with
  409 ``scope_not_allowed`` at create, update and run.
- Every query the intake sends is restricted to the allowlist (``project in (...) AND (<jql>)``),
  so issues of other projects are never fetched, also for a free JQL filter. The JQL is scanned with
  quotes and parentheses (``tools/jira_impl/_jira_jql_confine.py``): a query with
  unbalanced parentheses or quotes is never sent (the run is blocked as ``jql_unbalanced``).
- Every issue is checked again before it is mapped or persisted (a payload-provided issue, or a
  source that ignored the restriction). Its project is the one in its key, and a ``fields.project``
  that names another project disqualifies it. Dropped issues are reported only as
  ``filtered_outside_allowlist``, never with a count of another project's issues.
- A Jira write re-checks the allowlist at write time (:func:`writable_issue`), so an item synced
  before the allowlist was narrowed is no longer writable.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkItemSyncConfig
from ....tools.jira_impl._jira_jql_confine import confine_jql, jql_problem
from ..jira_values import object_value, project_key, string_list
from .jira_connector import _resolve_jira_connector_config

REASON_SCOPE_NOT_ALLOWED = "scope_not_allowed"
REASON_CONNECTION_UNAVAILABLE = "intake_connection_unavailable"
REASON_JQL_UNBALANCED = "jql_unbalanced"
_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")


def parse_allowed_projects(raw: object) -> frozenset[str] | None:
    """The allowlist as the agent tools read it; ``None`` when unrestricted."""
    if isinstance(raw, list):
        keys = [str(key).strip().upper() for key in raw if str(key).strip()]
    elif isinstance(raw, str):
        keys = [key.strip().upper() for key in raw.replace(",", " ").split() if key.strip()]
    else:
        return None
    return frozenset(keys) or None


async def intake_allowlist(db: AsyncSession, config: WorkItemSyncConfig) -> frozenset[str] | None:
    """The allowlist of the connection the intake uses (its ``connection_id``, narrowed to its bound projects).

    A named connection that is gone refuses the intake (409 ``intake_connection_unavailable``), never another one.
    """
    connection = await _resolve_jira_connector_config(db, config)
    if connection is None:
        unavailable = REASON_CONNECTION_UNAVAILABLE
        raise HTTPException(status_code=409, detail={"state": "needs_configuration", "reason": unavailable,
                                                     "code": unavailable})
    return parse_allowed_projects(connection.get("jira_allowed_projects"))


def refuse_outside_allowlist(filters: dict[str, Any] | None, allowed: frozenset[str] | None) -> None:
    """409 ``scope_not_allowed`` when the intake's project filter leaves the allowlist."""
    if allowed is None:
        return
    outside = sorted({key.upper() for key in string_list(object_value(filters).get("project_keys"))} - allowed)
    if outside:
        raise HTTPException(
            status_code=409,
            detail={"state": "refused", "reason": REASON_SCOPE_NOT_ALLOWED, "projects": outside},
        )


async def guard_intake(db: AsyncSession, config: WorkItemSyncConfig) -> frozenset[str] | None:
    """Refuse an intake outside the allowlist; answer the allowlist for the run."""
    allowed = await intake_allowlist(db, config)
    refuse_outside_allowlist(config.filters_json, allowed)
    return allowed


async def check_intake_config(db: AsyncSession, config: WorkItemSyncConfig) -> None:
    """At create and update: the allowlist and the status mapping targets.

    A refusal rolls the attempted change back, so a refused save never lingers in the session.
    """
    from ..workflow_lifecycle import validate_intake_status_targets

    try:
        await guard_intake(db, config)
        await validate_intake_status_targets(db, config)
    except HTTPException:
        await db.rollback()
        raise


def restrict_jql(jql: str, allowed: frozenset[str] | None) -> str:
    """``jql`` limited to the allowed projects, keeping its ``ORDER BY``; unchanged when unrestricted."""
    if allowed is None:
        return jql
    keys = sorted(key for key in allowed if _PROJECT_KEY.fullmatch(key))
    if not keys:
        # An allowlist with no usable key admits nothing: never an unrestricted query.
        raise HTTPException(
            status_code=409, detail={"state": "refused", "reason": REASON_SCOPE_NOT_ALLOWED, "projects": []}
        )
    # The body is confined by a quote- and parenthesis-aware scan; it can never escape the clause.
    return confine_jql(str(jql or ""), f"project in ({', '.join(keys)})")


def unsendable_query(jql: str) -> dict[str, Any] | None:
    """A blocked source (never sent) for an unsafe query; else ``None``.

    ``jql_unbalanced``: unbalanced parentheses or quotes; ``jql_invalid``: a backslash outside a quoted
    string.
    """
    problem = jql_problem(jql)
    if problem is None:
        return None
    message = ("The JQL has unbalanced parentheses or quotes" if problem == REASON_JQL_UNBALANCED
               else "The JQL has a backslash outside a quoted string")
    return {
        "configured": False,
        "issues": [],
        "source_count": 0,
        "source_complete": True,
        "metadata": {"reason": problem, "message": f"{message}; it was not sent to Jira."},
    }


def _key_project(source_key: object) -> str:
    key = str(source_key or "").strip().upper()
    project, separator, number = key.rpartition("-")
    return project if separator and number.isdigit() and _PROJECT_KEY.fullmatch(project) else ""


def issue_allowed(issue: dict[str, Any], allowed: frozenset[str] | None) -> bool:
    """Whether ``issue`` belongs to an allowed project (always, when unrestricted).

    The project is the one in the issue key; a ``fields.project`` naming another project is a
    contradiction, never a second chance.
    """
    if allowed is None:
        return True
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    from_key = _key_project(issue.get("key") or fields.get("key"))
    declared = str(project_key(issue, fields) or "").upper()
    if not from_key or (declared and declared != from_key):
        return False
    return from_key in allowed


def _linked_key(link: dict[str, Any]) -> str:
    linked = link.get("outwardIssue") or link.get("inwardIssue") or {}
    return str(linked.get("key") or "") if isinstance(linked, dict) else ""


def scope_links(links: Any, allowed: frozenset[str] | None) -> list[Any]:
    """Links to allowed projects as they are; any other becomes a key-less ``external`` marker."""
    if allowed is None or not isinstance(links, list):
        return links if isinstance(links, list) else []
    scoped: list[Any] = []
    for link in links:
        if isinstance(link, dict) and _key_project(_linked_key(link)) in allowed:
            scoped.append(link)
            continue
        kind = link.get("type") if isinstance(link, dict) and isinstance(link.get("type"), dict) else {}
        scoped.append({"type": {"name": kind.get("name")} if kind.get("name") else {}, "external": True})
    return scoped


def scope_parent(parent_key: object, allowed: frozenset[str] | None) -> object:
    """A parent of another project is not named on the item."""
    if allowed is None or not parent_key or _key_project(parent_key) in allowed:
        return parent_key
    return None


def writable_issue(source_key: object, allowed: frozenset[str] | None) -> None:
    """409 ``scope_not_allowed`` before any Jira write to an issue outside the allowlist."""
    if allowed is None:
        return
    project = _key_project(source_key)
    if project not in allowed:
        raise HTTPException(
            status_code=409,
            detail={"state": "refused", "reason": REASON_SCOPE_NOT_ALLOWED, "projects": [project] if project else []},
        )


__all__ = [
    "REASON_JQL_UNBALANCED",
    "REASON_SCOPE_NOT_ALLOWED",
    "check_intake_config",
    "guard_intake",
    "intake_allowlist",
    "issue_allowed",
    "parse_allowed_projects",
    "refuse_outside_allowlist",
    "restrict_jql",
    "scope_links",
    "scope_parent",
    "unsendable_query",
    "writable_issue",
]
