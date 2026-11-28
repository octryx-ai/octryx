"""Compare one Workspace's governed ledger references with its object inventory. Report-only: inventory first, then the
ledger. A legal hold skips the Workspace, a live retention hold its object."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from ....models.project.knowledge_evidence import KnowledgeSourceRevision
from ....time_utils import utc_now, utc_now_aware
from ..identity.workspace import WorkspaceId
from ..objects import (
    InventoryObject,
    KnowledgeObjectError,
    KnowledgeObjectMaintenance,
    KnowledgeObjectNotConfiguredError,
    KnowledgeObjectUnauthorizedError,
    KnowledgeObjectUnavailableError,
)
from ..retrieval.errors import KnowledgeRetrievalError
from .errors import (
    InvalidRetentionRequestError,
    RetentionContractError,
    RetentionError,
    RetentionNotConfiguredError,
    RetentionRecordNotFoundError,
    RetentionUnauthorizedError,
    RetentionUnavailableError,
)
from .failures import failure_token
from .holds import held_object_keys
from .policy import load_retention_policy, normalize_operator
from .reconcile_record import ReconciliationReport, _record_failed_run, _record_legal_hold_run, _record_run

logger = logging.getLogger(__name__)

MAX_INVENTORY_PAGES = 20


def workspace_of(project_id: object) -> WorkspaceId:
    try:
        return WorkspaceId.parse(project_id)
    except KnowledgeRetrievalError:
        # Raised outside the handler so no knowledge-layer error is chained as context.
        pass
    raise InvalidRetentionRequestError()


async def require_workspace(db: AsyncSession, project_id: object) -> WorkspaceId:
    workspace = workspace_of(project_id)
    row = (await db.execute(select(Project.id).where(Project.id == workspace.canonical))).scalar_one_or_none()
    if row is None:
        raise RetentionRecordNotFoundError()
    return workspace


async def reconcile_workspace(
    db: AsyncSession,
    *,
    maintenance: KnowledgeObjectMaintenance,
    project_id: str,
    requested_by: str,
    now: datetime | None = None,
) -> ReconciliationReport:
    if type(maintenance) is not KnowledgeObjectMaintenance:
        raise RetentionContractError()
    workspace = await require_workspace(db, project_id)
    operator = normalize_operator(requested_by)
    # Timezone-aware by default and strictly aware when injected: the age bound decides
    # eligibility, so the instant it is measured against may not be one whose zone has to
    # be inferred. An offset-naive value is refused, never assumed to be
    # UTC, and the aware value is normalised once for the naive-UTC persistence convention.
    moment = now if now is not None else utc_now_aware()
    if type(moment) is not datetime or moment.tzinfo is None or moment.utcoffset() is None:
        raise InvalidRetentionRequestError()
    observed_at = moment.astimezone(UTC).replace(tzinfo=None)
    policy = await load_retention_policy(db, workspace.canonical)
    started_at = utc_now()
    if policy.legal_hold:
        return await _record_legal_hold_run(
            db, project_id=workspace.canonical, policy=policy, operator=operator, started_at=started_at
        )

    failed: tuple[RetentionError, str] | None = None
    inventory: tuple[InventoryObject, ...] = ()
    unrecognized = 0
    truncated = False
    try:
        inventory, unrecognized, truncated = await _inventory(maintenance, workspace)
    except KnowledgeObjectError as error:
        failed = (_mapped_failure(error), failure_token(error))
    if failed is not None:
        state, token = failed
        await _record_failed_run(
            db,
            project_id=workspace.canonical,
            policy=policy,
            operator=operator,
            started_at=started_at,
            failure=token,
        )
        # Raised outside the handler, so no object-store error is chained as this state's
        # context: its traceback references the signed request that produced it.
        raise state

    # A held key belongs to the pass that holds it: never a finding of this one.
    referenced = await _referenced_keys(db, workspace.canonical) | await held_object_keys(
        db, project_id=workspace.canonical, now=observed_at
    )
    return await _record_run(
        db,
        workspace=workspace,
        policy=policy,
        operator=operator,
        started_at=started_at,
        observed_at=observed_at,
        inventory=inventory,
        referenced=referenced,
        unrecognized=unrecognized,
        truncated=truncated,
    )


async def record_failed_run(db: AsyncSession, *, project_id: str, requested_by: str, failure: str) -> None:
    workspace = await require_workspace(db, project_id)
    await _record_failed_run(
        db,
        project_id=workspace.canonical,
        policy=await load_retention_policy(db, workspace.canonical),
        operator=normalize_operator(requested_by),
        started_at=utc_now(),
        failure=failure,
    )


def _mapped_failure(error: KnowledgeObjectError) -> RetentionError:
    if isinstance(error, KnowledgeObjectNotConfiguredError):
        return RetentionNotConfiguredError()
    if isinstance(error, KnowledgeObjectUnauthorizedError):
        return RetentionUnauthorizedError()
    if isinstance(error, KnowledgeObjectUnavailableError):
        return RetentionUnavailableError()
    return RetentionContractError()


async def _inventory(
    maintenance: KnowledgeObjectMaintenance, workspace: WorkspaceId
) -> tuple[tuple[InventoryObject, ...], int, bool]:
    objects: list[InventoryObject] = []
    unrecognized = 0
    after_key: str | None = None
    for _ in range(MAX_INVENTORY_PAGES):
        page = await maintenance.list_workspace(workspace, after_key=after_key)
        objects.extend(page.objects)
        unrecognized += page.unrecognized_count
        if not page.truncated or page.next_after_key is None:
            # Complete, or the server reported more but gave no usable cursor: either way
            # this pass stops here, and ``page.truncated`` decides how it is recorded.
            return tuple(objects), unrecognized, page.truncated and page.next_after_key is None
        after_key = page.next_after_key
    logger.warning(
        "Knowledge object inventory hit the page bound: workspace=%s pages=%d",
        workspace.canonical,
        MAX_INVENTORY_PAGES,
    )
    return tuple(objects), unrecognized, True


async def _referenced_keys(db: AsyncSession, project_id: str) -> set[str]:
    # Only the configured bucket is read, so a committed revision's key counts whatever bucket it recorded.
    rows = await db.execute(
        select(KnowledgeSourceRevision.object_key).where(KnowledgeSourceRevision.project_id == project_id)
    )
    return {row[0] for row in rows.all() if type(row[0]) is str}
