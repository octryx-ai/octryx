"""A coding session's Bitbucket pull request: the reviewers it asks for and the record it leaves."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkItem, WorkItemChangeUnit
from ..jira_values import blank_to_none, object_value, string_list
from ..reviewers import recommend_reviewers_for_work_item


async def reviewer_contract_for_bitbucket_pr_tool(
    db: AsyncSession | None,
    *,
    session_id: str,
    project_key: str,
    repo_slug: str,
    from_branch: str,
    explicit_reviewers: Any,
) -> dict[str, Any]:
    reviewers = string_list(explicit_reviewers)
    if reviewers:
        return {
            "source": "tool_parameters",
            "reviewers": reviewers,
            "recommendation_evidence": [],
            "missing_setup": [],
        }
    if db is None:
        return {"source": "unavailable", "reviewers": [], "recommendation_evidence": [], "missing_setup": ["database"]}
    resolved = await resolve_coding_pr_work_context(
        db,
        session_id=session_id,
        project_key=project_key,
        repo_slug=repo_slug,
        branch_name=from_branch,
    )
    item = resolved.get("work_item")
    if not isinstance(item, WorkItem):
        return {
            "source": "unavailable",
            "reviewers": [],
            "recommendation_evidence": [],
            "missing_setup": ["work_item_session_link"],
        }
    recommendation_payload = await recommend_reviewers_for_work_item(
        db, item.id, viewer=await db.get(User, resolved["session_user_id"]), workspace_id=resolved["workspace_id"])
    selected = await _bitbucket_reviewer_usernames(db, recommendation_payload)
    return {
        "source": "repository_record",
        "reviewers": selected["reviewers"],
        "recommendation_evidence": selected["evidence"],
        "missing_setup": sorted(
            {
                *string_list(recommendation_payload.get("missing_setup")),
                *selected["missing_setup"],
            }
        ),
        "work_item_id": item.id,
        "source_key": item.source_key,
    }


async def resolve_coding_pr_work_context(
    db: AsyncSession,
    *,
    session_id: str,
    project_key: str,
    repo_slug: str,
    branch_name: str,
) -> dict[str, Any]:
    # The work item only from the session's own Workspace.
    session = await db.get(Session, session_id)
    metadata = object_value(session.metadata_ if session else None)
    execution = object_value(metadata.get("secure_work_execution"))
    workspace_id = session.project_id if session else None
    item = await _work_item_from_execution(db, execution)
    if item is None or not workspace_id or item.project_id != workspace_id:
        return {"work_item": None, "change_unit": None, "workspace_id": workspace_id, "session_user_id": None}
    units = await _work_item_units(db, item.id)
    unit = _match_change_unit(units, repo_slug=repo_slug, branch_name=branch_name)
    return {"work_item": item, "change_unit": unit, "workspace_id": workspace_id, "session_user_id": session.user_id}


async def _work_item_from_execution(db: AsyncSession, execution: dict[str, Any]) -> WorkItem | None:
    work_item_id = blank_to_none(execution.get("work_item_id"))
    if not work_item_id:
        return None
    return await db.get(WorkItem, work_item_id)


async def _work_item_units(db: AsyncSession, work_item_id: str) -> list[WorkItemChangeUnit]:
    return list(
        (
            await db.execute(
                select(WorkItemChangeUnit)
                .where(WorkItemChangeUnit.work_item_id == work_item_id)
                .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
            )
        ).scalars()
    )


def _match_change_unit(
    units: list[WorkItemChangeUnit],
    *,
    repo_slug: str,
    branch_name: str,
) -> WorkItemChangeUnit | None:
    normalized_repo = _repo_token(repo_slug)
    normalized_branch = branch_name.strip()
    return (
        next(
            (
                unit
                for unit in units
                if (
                    normalized_branch
                    and unit.branch_name == normalized_branch
                    and _repo_token(unit.repository_name) == normalized_repo
                )
            ),
            None,
        )
        or next((unit for unit in units if normalized_branch and unit.branch_name == normalized_branch), None)
        or next((unit for unit in units if _repo_token(unit.repository_name) == normalized_repo), None)
        or (units[0] if len(units) == 1 else None)
    )


async def _bitbucket_reviewer_usernames(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    selected: list[str] = []
    evidence: list[dict[str, Any]] = []
    missing_setup: set[str] = set()
    recommendations = payload.get("recommendations") if isinstance(payload.get("recommendations"), list) else []
    for candidate in recommendations:
        if not isinstance(candidate, dict) or not candidate.get("available") or int(candidate.get("score") or 0) <= 0:
            continue
        username = str(candidate.get("scm_username") or "").strip()
        if not username:
            continue
        selected.append(username)
        evidence.append({"user_id": candidate.get("user_id"), "display_name": candidate.get("display_name"),
                         "score": candidate.get("score"), "selected_bitbucket_username": username})
        if len(selected) >= 2:
            break
    if not selected:
        missing_setup.add("bitbucket_username")
    return {"reviewers": selected, "evidence": evidence, "missing_setup": sorted(missing_setup)}


def _repo_token(value: str | None) -> str:
    return str(value or "").strip().rstrip("/").split("/")[-1].lower()


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in ("id", "title", "state", "status", "from_branch", "to_branch", "links", "status_code")
        if key in result
    }
