"""A coding session's Bitbucket pull request: the reviewers it asks for and the record it leaves.

Both resolve the session's Work Item from its execution metadata and accept it only in the session's current
Workspace (``Session.project_id``, the Workspace the turn resolved; an item of another Workspace answers like no
linked item). That Workspace is passed to the reviewer recommendation and the pull request record.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Session, User, WorkItem, WorkItemChangeUnit
from ...named_connections.service_config import planned_tool_config
from ..jira_values import blank_to_none, object_value, string_list
from ..lifecycle_transitions import STATE_REVIEW, auto_transition_work_item
from ..pull_requests.pull_requests import sync_pull_request
from ..pull_requests.record_identity import answered_pull_request, pull_request_identity
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


async def record_bitbucket_pull_request_delivery(
    db: AsyncSession | None,
    *,
    session_id: str,
    user_id: str,
    tool_params: dict[str, Any],
    tool_result: dict[str, Any],
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if db is None or tool_result.get("error"):
        return None
    pr_id, pr_url = answered_pull_request(tool_result)
    if not pr_id or not pr_url:
        return {
            "status": "not_recorded",
            "reason": "missing_pr_identity",
            "required": ["id", "links"],
        }

    project_key = str(tool_params.get("project_key") or tool_result.get("project_key") or "").strip()
    repo_slug = str(tool_params.get("repo_slug") or tool_result.get("repo_slug") or "").strip()
    from_branch = str(tool_params.get("from_branch") or tool_result.get("from_branch") or "").strip()
    target_branch = str(tool_params.get("to_branch") or tool_result.get("to_branch") or "").strip()
    resolved = await resolve_coding_pr_work_context(
        db,
        session_id=session_id,
        project_key=project_key,
        repo_slug=repo_slug,
        branch_name=from_branch,
    )
    user = await db.get(User, user_id)
    if user is None:
        return {"status": "not_recorded", "reason": "user_not_found"}

    item = resolved.get("work_item")
    if not isinstance(item, WorkItem):  # a PR is recorded for its Work Item only
        return {"status": "not_recorded", "reason": "no_work_item"}
    unit = resolved.get("change_unit")
    reviewers = _reviewers_from_result_or_params(tool_result, tool_params)
    payload = {
        "work_item_id": item.id,
        "change_unit_id": unit.id if isinstance(unit, WorkItemChangeUnit) else None,
        "identity": pull_request_identity("bitbucket", pr_url, f"{project_key}/{repo_slug}", pr_id),
        "repository_url": _repository_url(planned_tool_config("create_bitbucket_pull_request", tool_params,
                                                              project_config),
                                          project_key=project_key, repo_slug=repo_slug, pr_url=pr_url),
        "pr_url": pr_url,
        "title": blank_to_none(tool_result.get("title") or tool_params.get("title")),
        "source_branch": from_branch or blank_to_none(tool_result.get("from_branch")),
        "target_branch": target_branch or blank_to_none(tool_result.get("to_branch")),
        "status": _work_pr_status(tool_result),
        "reviewers": reviewers,
        "raw_summary": {
            "tool_result": _compact_result(tool_result),
            "delivery_contract": "coding_bitbucket_pr_delivery.v1",
        },
    }
    synced = await sync_pull_request(db, current_user=user, workspace_id=resolved["workspace_id"], payload=payload)
    lifecycle_transition = await auto_transition_work_item(
        db,
        item=item,
        current_user=user,
        to_state=STATE_REVIEW,
        reason=f"Pull request created: {pr_url}",
    )
    return {
        "status": "recorded",
        "work_pull_request": synced,
        "work_item_id": payload["work_item_id"],
        "change_unit_id": payload["change_unit_id"],
        "reviewers": reviewers,
        "lifecycle_transition": lifecycle_transition,
    }


async def resolve_coding_pr_work_context(
    db: AsyncSession,
    *,
    session_id: str,
    project_key: str,
    repo_slug: str,
    branch_name: str,
) -> dict[str, Any]:
    """``work_item`` (only in the session's Workspace), its matched ``change_unit``, ``workspace_id`` (the session's)
    and ``session_user_id``."""
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
    """The first two suggested reviewers with a declared source-control username (the repository record's
    ``default_reviewers``); a suggestion without one is skipped and reported as missing setup."""
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


def _reviewers_from_result_or_params(tool_result: dict[str, Any], tool_params: dict[str, Any]) -> list[Any]:
    result_reviewers = tool_result.get("reviewers")
    if isinstance(result_reviewers, list) and result_reviewers:
        return result_reviewers
    return string_list(tool_params.get("reviewers"))


def _work_pr_status(tool_result: dict[str, Any]) -> str:
    state = str(tool_result.get("state") or "").strip().lower()
    if state:
        return state
    status = str(tool_result.get("status") or "").strip().lower()
    if status in {"created", "existing", "updated"}:
        return "open"
    return status or "open"


def _repository_url(
    project_config: dict[str, Any] | None,
    *,
    project_key: str,
    repo_slug: str,
    pr_url: str,
) -> str | None:
    """The repository's web URL on the connection the pull request ran on (Bitbucket Server path layout); a
    Bitbucket Cloud connection (or none) takes it from the pull request URL."""
    config = project_config or {}
    base_url = str(config.get("bitbucket_url") or "").strip()
    cloud = str(config.get("bitbucket_deployment") or "").strip().lower() == "cloud"
    if base_url and project_key and repo_slug and not cloud:
        return urljoin(base_url.rstrip("/") + "/", f"projects/{project_key}/repos/{repo_slug}")
    marker = "/pull-requests/"
    if marker in pr_url:
        return pr_url.split(marker, 1)[0]
    return None


def _repo_token(value: str | None) -> str:
    return str(value or "").strip().rstrip("/").split("/")[-1].lower()


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in ("id", "title", "state", "status", "from_branch", "to_branch", "links", "status_code")
        if key in result
    }
