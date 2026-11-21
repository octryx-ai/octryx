"""Operator transport for Knowledge object retention.

Thin by design, and *narrower* than the service it fronts: this router can read and set the
retention policy and read the newest reconciliation report. It deliberately **cannot** trigger
an inventory or a deletion, so the API process needs no ``s3:ListBucket`` and no
``s3:DeleteObject`` grant at all.

Two access gates, both required: global admin (retention is an instance-operator decision,
not a project-admin one) and the Workspace authorization of the Knowledge feature, so an
unknown Workspace, one the caller cannot reach, and a malformed id all render the same 404
body and this surface cannot be used to enumerate Workspaces.

Nothing in a response names an object: a finding is a uuid plus its size, age and state. No
object key, content address, bucket, endpoint, prefix or credential is rendered here, and no
dependency message is ever surfaced — only this module's fixed state texts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...models.project.knowledge_object_retention import (
    ALL_RETENTION_MODES,
    DEFAULT_MIN_OBJECT_AGE_HOURS,
    MAX_OBJECT_AGE_HOURS,
    MIN_OBJECT_AGE_HOURS,
    RETENTION_MODE_REPORT_ONLY,
)
from ...services.auth import get_current_user
from ...services.auth.admin_principal import get_current_admin_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import WORKSPACE_NOT_FOUND_DETAIL, EvidenceLedgerError
from ...services.knowledge.retention.errors import RetentionError, RetentionState
from ...services.knowledge.retention.policy import load_retention_policy, set_retention_policy
from ...services.knowledge.retention.reports import DEFAULT_REPORT_FINDINGS, MAX_REPORT_FINDINGS, latest_run_report
from ...services.notification_delivery import require_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/knowledge/retention/workspaces/{workspace_id}",
    tags=["workspace-knowledge-retention"],
)

# One fixed detail per state; no dependency text, object key or configuration value.
_STATUS_BY_STATE = {
    RetentionState.NOT_FOUND: (404, WORKSPACE_NOT_FOUND_DETAIL),
    RetentionState.INVALID_REQUEST: (400, "Invalid knowledge object retention request."),
    RetentionState.NEEDS_CONFIGURATION: (503, "Workspace knowledge object storage is not configured."),
    RetentionState.UNAVAILABLE: (503, "Workspace knowledge object storage is unavailable."),
    RetentionState.UNAUTHORIZED: (502, "Workspace knowledge object storage rejected the identity."),
    RetentionState.CONTRACT_VIOLATION: (502, "Workspace knowledge retention dependency failed."),
}
_FALLBACK_STATUS = (502, "Workspace knowledge retention dependency failed.")


def _http_error(error: RetentionError) -> HTTPException:
    status_code, detail = _STATUS_BY_STATE.get(error.state, _FALLBACK_STATUS)
    logger.info("Knowledge object retention request refused: state=%s", error.state.value)
    return HTTPException(status_code=status_code, detail=detail)


class RetentionPolicyRequest(BaseModel):
    mode: str = Field(
        default=RETENTION_MODE_REPORT_ONLY,
        description=f"One of {sorted(ALL_RETENTION_MODES)}.",
    )
    min_object_age_hours: int = Field(
        default=DEFAULT_MIN_OBJECT_AGE_HOURS, ge=MIN_OBJECT_AGE_HOURS, le=MAX_OBJECT_AGE_HOURS
    )
    legal_hold: bool = Field(default=False, description="Records a legal hold on this Workspace's objects.")


async def _authorized_workspace(db: AsyncSession, current_user: User, workspace_id: str) -> str:
    """Global admin first, then the Knowledge feature's indistinguishable 404."""
    await require_admin_user(db, current_user)
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
    except WorkspaceWriteForbiddenError:
        # Unreachable while a global admin resolves to the ``admin`` project role, and handled
        # anyway so a change in that resolution surfaces as 403 rather than as a 500.
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError:
        raise HTTPException(status_code=404, detail=WORKSPACE_NOT_FOUND_DETAIL) from None
    return authorized.project_id


def _policy_payload(policy) -> dict:
    return {
        "workspace_id": policy.project_id,
        "mode": policy.mode,
        "min_object_age_hours": policy.min_object_age_hours,
        "legal_hold": policy.legal_hold,
        # False means no policy row exists, i.e. the report-only default.
        "explicit": policy.explicit,
    }


@router.get("/policy")
async def get_object_retention_policy(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The effective retention policy; an absent row reports the report-only default."""
    project_id = await _authorized_workspace(db, current_user, workspace_id)
    try:
        return _policy_payload(await load_retention_policy(db, project_id))
    except RetentionError as error:
        raise _http_error(error) from None


@router.put("/policy")
async def put_object_retention_policy(
    workspace_id: str,
    request: RetentionPolicyRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record this Workspace's explicit retention decision."""
    project_id = await _authorized_workspace(db, current_user, workspace_id)
    try:
        policy = await set_retention_policy(
            db,
            project_id=project_id,
            mode=request.mode,
            min_object_age_hours=request.min_object_age_hours,
            legal_hold=request.legal_hold,
            updated_by=current_user.id,
        )
    except RetentionError as error:
        raise _http_error(error) from None
    return _policy_payload(policy)


@router.get("/runs/latest")
async def get_latest_reconciliation_report(
    workspace_id: str,
    limit: int | None = Query(default=None, ge=1, le=MAX_REPORT_FINDINGS),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Counts and findings of the newest run; ``reconciled`` is false before the first one."""
    project_id = await _authorized_workspace(db, current_user, workspace_id)
    try:
        report = await latest_run_report(
            db, project_id, limit=limit if limit is not None else DEFAULT_REPORT_FINDINGS
        )
    except RetentionError as error:
        raise _http_error(error) from None
    if report is None:
        return {"workspace_id": project_id, "reconciled": False}
    return {
        "workspace_id": project_id,
        "reconciled": True,
        "run_id": report.run_id,
        "state": report.state,
        "failure": report.failure,
        "mode": report.mode,
        "min_object_age_hours": report.min_object_age_hours,
        "requested_by": report.requested_by,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "counts": {
            "inventory_objects": report.inventory_object_count,
            "referenced_objects": report.referenced_object_count,
            "unreferenced_objects": report.unreferenced_object_count,
            "unrecognized_objects": report.unrecognized_object_count,
            "deletion_candidates": report.candidate_object_count,
            "unreferenced_bytes": report.unreferenced_byte_size,
        },
        "inventory_truncated": report.inventory_truncated,
        "findings_truncated": report.findings_truncated,
        # A finding is a uuid plus measurements: nothing here locates or identifies content.
        "findings": [
            {
                "finding_id": finding.finding_id,
                "byte_size": finding.byte_size,
                "observed_age_hours": finding.observed_age_hours,
                "age_eligible": finding.age_eligible,
                "state": finding.state,
            }
            for finding in report.findings
        ],
    }

