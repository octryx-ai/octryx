"""The internal pull request record (``work_pull_requests``); there is no user-facing sync, refresh or reviewer route.

Written when a workflow run or a coding session opens a pull request for a Work Item
(``workflow_runs/platform/pr_details``, ``coding/coding_pr_delivery``) and read again from the host by the refresh
worker (``refresh``). A record always belongs to a Work Item of the Workspace the run or coding session resolved
(``workspace_id``; an item of another Workspace answers like a missing one). Its identity is exact: ``scope_key``
(that Workspace) + the identity the caller derived when the pull request was opened (``record_identity``); a Work
Item never changes Workspace after creation (``workspace_immutable``), so a record's scope stays its item's.

The change unit a record names must be its item's own; the repository profile (the unit's) is loaded through
``related_rows`` for that Workspace: by the acting user when the record is written, by the record's creator when it
is refreshed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, User, WorkItem, WorkItemChangeUnit, WorkPullRequest, WorkRepositoryProfile
from ....time_utils import utc_now
from ..jira_values import blank_to_none, list_value, object_value, string_list
from ..related_rows import REPOSITORY_PROFILE, load_optional_related, load_usable_related
from ..serializers import serialize_pull_request
from .pull_request_values import identity_token, mismatch, object_or_string_list
from .record_identity import IDENTITY_COLUMNS, in_item_workspace

FAILED_BUILD_STATUSES = {"failed", "failure", "error", "blocked", "aborted", "unstable"}
OPEN_PR_STATUSES = {"open", "opened", "active", "in_review", "review"}
STALE_DAYS = 7


async def sync_pull_request(
    db: AsyncSession, *, current_user: User, workspace_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Record (or update) the pull request a run or coding session opened for ``payload["work_item_id"]``;
    ``workspace_id`` is the run's or session's resolved Workspace, the item's and the record's scope;
    ``payload["identity"]`` is the pull request's identity (``record_identity.pull_request_identity``)."""
    item = await db.get(WorkItem, payload["work_item_id"])
    if item is None or not workspace_id or item.project_id != workspace_id:
        raise HTTPException(status_code=404, detail="Work Item not found")
    unit_id = blank_to_none(payload.get("change_unit_id"))
    unit = await item_unit(db, unit_id, item.id) if unit_id else None
    if unit_id and unit is None:
        raise HTTPException(status_code=404, detail="Change Unit not found for this Work Item")
    profile = await load_optional_related(db, current_user, REPOSITORY_PROFILE,
                                          unit.repository_profile_id if unit else None, for_workspace=workspace_id)
    normalized = _normalize_payload(payload, item=item, unit=unit, profile=profile)
    existing = await find_record(db, scope_key=normalized["scope_key"], identity=normalized)
    row = existing or WorkPullRequest(created_by=current_user.id, **normalized)
    if existing:
        for key, value in normalized.items():
            setattr(row, key, value)
        row.updated_by = current_user.id
    db.add(row)
    await db.flush()
    row.mismatch_json = await detect_mismatches(db, row, profile)
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.pull_request_synced",
            resource_type="secure_work_pull_request",
            resource_id=row.id,
            details={
                "work_item_id": row.work_item_id,
                "change_unit_id": row.change_unit_id,
                "repository_slug": row.repository_slug,
                "pr_id": row.pr_id,
                "status": row.status,
                "mismatch_count": len(row.mismatch_json or []),
            },
        )
    )
    await db.flush()
    result = serialize_pull_request(row)
    result["created"] = existing is None
    return result


async def item_unit(db: AsyncSession, unit_id: str, work_item_id: str | None) -> WorkItemChangeUnit | None:
    """The change unit ``unit_id`` when it is the item's own, else ``None``."""
    unit = await db.get(WorkItemChangeUnit, unit_id)
    return unit if unit is not None and work_item_id and unit.work_item_id == work_item_id else None


async def recorded_profile(db: AsyncSession, row: WorkPullRequest) -> WorkRepositoryProfile | None:
    """A stored record's repository profile through the scoped loader, as its creator, for the record's Workspace
    (``scope_key``, checked against its item's by ``host_target.workspace_of`` before the refresh reads).

    A reference the creator may no longer use or that no longer fits that Workspace is removed from the record
    (never used, never serialized)."""
    if not row.repository_profile_id:
        return None
    profile = await load_usable_related(db, await db.get(User, row.created_by), REPOSITORY_PROFILE,
                                        row.repository_profile_id, for_workspace=row.scope_key)
    if profile is None:
        row.repository_profile_id = None
    return profile


def _normalize_payload(
    payload: dict[str, Any], *, item: WorkItem, unit: WorkItemChangeUnit | None,
    profile: WorkRepositoryProfile | None,
) -> dict[str, Any]:
    repository_url = blank_to_none(payload.get("repository_url")) or (profile.repository_url if profile else None)
    return {
        "work_item_id": item.id,
        "scope_key": item.project_id,
        "change_unit_id": unit.id if unit else None,
        "repository_profile_id": profile.id if profile else None,
        **{column: payload["identity"][column] for column in IDENTITY_COLUMNS},
        "repository_url": repository_url,
        "pr_url": str(payload["pr_url"]).strip(),
        "title": blank_to_none(payload.get("title")),
        "source_branch": blank_to_none(payload.get("source_branch")) or (unit.branch_name if unit else None),
        "target_branch": blank_to_none(payload.get("target_branch")),
        "status": str(payload.get("status") or "open").strip().lower()[:80],
        "reviewers_json": object_or_string_list(payload.get("reviewers")),
        "linked_jira_keys_json": [item.source_key],
        "mismatch_json": [],
        "raw_summary_json": object_value(payload.get("raw_summary")),
        "last_synced_at": utc_now(),
        "updated_by": None,
    }


async def find_record(db: AsyncSession, *, scope_key: str, identity: dict[str, Any]) -> WorkPullRequest | None:
    """The record of this exact identity (``record_identity.pull_request_identity``) in the Workspace ``scope_key``,
    bound to a Work Item of that Workspace."""
    return (await db.execute(select(WorkPullRequest).where(
        WorkPullRequest.scope_key == scope_key, in_item_workspace(),
        *(getattr(WorkPullRequest, column) == identity[column] for column in IDENTITY_COLUMNS),
    ))).scalar_one_or_none()


async def detect_mismatches(
    db: AsyncSession, row: WorkPullRequest, profile: WorkRepositoryProfile | None
) -> list[dict[str, Any]]:
    """``profile``: the record's repository profile as the scoped loader returned it (or none)."""
    mismatches: list[dict[str, Any]] = []
    unit = await item_unit(db, row.change_unit_id, row.work_item_id) if row.change_unit_id else None
    policy = object_value(unit.reviewer_policy_json) if unit else {}
    expected_target = blank_to_none(policy.get("target_branch")) or (
        (blank_to_none(profile.pr_target_branch) or blank_to_none(profile.default_branch)) if profile else None)
    if expected_target and row.target_branch and row.target_branch != expected_target:
        mismatches.append(
            mismatch(
                "wrong_target_branch",
                f"Target branch is {row.target_branch}, expected {expected_target}.",
                "block",
                {"expected": expected_target, "actual": row.target_branch},
            )
        )
    build_status = (row.build_status or "").strip().lower()
    if build_status in FAILED_BUILD_STATUSES:
        mismatches.append(mismatch("failed_pipeline", f"Build status is {row.build_status}.", "block"))
    reviewer_gap = _reviewer_gap(row, policy)
    if reviewer_gap:
        mismatches.append(reviewer_gap)
    if _is_stale(row):
        mismatches.append(
            mismatch(
                "stale_pr",
                f"Open PR has not changed for at least {STALE_DAYS} days.",
                "review",
                {"stale_days": STALE_DAYS},
            )
        )
    return mismatches


def _reviewer_gap(row: WorkPullRequest, policy: dict[str, Any]) -> dict[str, Any] | None:
    expected = set(string_list(policy.get("required_reviewers")))
    expected.update(string_list(policy.get("default_reviewers")))
    if not expected:
        return None
    actual = {identity_token(entry) for entry in list_value(row.reviewers_json)}
    actual.update(identity_token(entry) for entry in list_value(row.approvals_json))
    actual.discard("")
    missing = sorted(expected - actual)
    if not missing:
        return None
    return mismatch(
        "missing_reviewer",
        "Required reviewer is not assigned or has not approved.",
        "review",
        {"missing_reviewers": missing},
    )


def _is_stale(row: WorkPullRequest) -> bool:
    updated_at = row.source_updated_at or row.updated_at
    if not updated_at or row.status not in OPEN_PR_STATUSES:
        return False
    return updated_at <= utc_now() - timedelta(days=STALE_DAYS)


__all__ = ["detect_mismatches", "find_record", "item_unit", "recorded_profile", "sync_pull_request"]
