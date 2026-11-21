"""Compare one Workspace's governed ledger references with its object inventory.

Report-only by construction: this module writes PostgreSQL governance rows and never calls
a deleting operation; no product path deletes a Knowledge object.

Two ordering rules make the comparison conservative rather than eager:

1. **Inventory first, ledger second.** A revision committed while the pages are being
   listed is then included in the reference set, so a freshly referenced object is reported
   as referenced. The reverse order would report it as unreferenced.
2. **Age eligibility is decided here and persisted per finding.** An object younger than
   the policy's ``min_object_age_hours`` is recorded as an observation but marked
   ineligible. The instant it is measured against is timezone-aware —
   :func:`~app.time_utils.utc_now_aware` by default, and an injected clock must be aware too,
   because an offset-naive value would decide the age bound on an inferred zone. It is
   normalised to the naive-UTC persistence convention exactly once.

A new run supersedes every earlier ``observed`` finding of the same Workspace, in the same
transaction that writes the new ones, and that transaction holds the Workspace's governance
boundary (``governance_lock.py``), so only the newest run's findings describe the bucket.

Bounds: the inventory is read in at most :data:`MAX_INVENTORY_PAGES` pages of at most
``MAX_INVENTORY_PAGE_KEYS`` keys. Reaching the bound sets ``inventory_truncated``, so a
partial view is visible as partial instead of being mistaken for "the whole Workspace".

Nothing about the bucket, endpoint, credential or object key is returned: a report carries
counts, finding ids, sizes and ages only.

The write side of a run (run row, findings, supersession) lives in ``reconcile_record``.
"""

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
from .policy import load_retention_policy, normalize_operator
from .reconcile_record import ReconciliationReport, _record_failed_run, _record_run

logger = logging.getLogger(__name__)

MAX_INVENTORY_PAGES = 20


def workspace_of(project_id: object) -> WorkspaceId:
    """The Workspace identity of a project id, or an explicit invalid-request state."""
    try:
        return WorkspaceId.parse(project_id)
    except KnowledgeRetrievalError:
        # Raised outside the handler so no knowledge-layer error is chained as context.
        pass
    raise InvalidRetentionRequestError()


async def require_workspace(db: AsyncSession, project_id: object) -> WorkspaceId:
    """Parse and confirm the Workspace exists; unknown is ``not_found``."""
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
    """Record one report-only reconciliation run for exactly one Workspace."""
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

    referenced = await _referenced_keys(db, workspace.canonical)
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


def _mapped_failure(error: KnowledgeObjectError) -> RetentionError:
    """Map an object-boundary failure onto this slice's states, retaining nothing."""
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
    """Read the Workspace's inventory in bounded pages: objects, unrecognized, truncated."""
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
    """Every object key this Workspace's committed revisions point at, whatever bucket they recorded.

    The configured bucket is the only one read (``objects/store.py``), so each committed revision's key counts
    as referenced regardless of the bucket the revision recorded.
    """
    rows = await db.execute(
        select(KnowledgeSourceRevision.object_key).where(KnowledgeSourceRevision.project_id == project_id)
    )
    return {row[0] for row in rows.all() if type(row[0]) is str}
