"""The explicit retention policy of one Workspace, and the operator identity token. No row means report-only."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_object_retention import (
    ALL_RETENTION_MODES,
    DEFAULT_MIN_OBJECT_AGE_HOURS,
    MAX_OBJECT_AGE_HOURS,
    MAX_OPERATOR_CHARS,
    MIN_OBJECT_AGE_HOURS,
    RETENTION_MODE_REPORT_ONLY,
    KnowledgeObjectRetentionPolicy,
)
from ....time_utils import utc_now
from .errors import InvalidRetentionRequestError
from .governance_lock import lock_workspace_governance

logger = logging.getLogger(__name__)

# Who ran a reconciliation: ``job:<name>``, ``cli:<name>`` or ``api:<user id>``. A narrow
# charset, because this token is persisted and printed in operator output.
_OPERATOR = re.compile(r"^[a-z]{2,12}:[A-Za-z0-9._@-]{1,50}$")


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    project_id: str
    mode: str
    min_object_age_hours: int
    legal_hold: bool
    explicit: bool


def default_policy(project_id: str) -> RetentionPolicy:
    return RetentionPolicy(
        project_id=project_id,
        mode=RETENTION_MODE_REPORT_ONLY,
        min_object_age_hours=DEFAULT_MIN_OBJECT_AGE_HOURS,
        legal_hold=False,
        explicit=False,
    )


def normalize_operator(value: object) -> str:
    if type(value) is not str or len(value) > MAX_OPERATOR_CHARS or not _OPERATOR.fullmatch(value):
        raise InvalidRetentionRequestError()
    return value


def policy_from_row(project_id: str, row: KnowledgeObjectRetentionPolicy | None) -> RetentionPolicy:
    if row is None:
        return default_policy(project_id)
    mode = str(row.mode)
    if mode not in ALL_RETENTION_MODES:
        # An unknown persisted mode is not a reason to guess: fail closed to report-only.
        logger.error("Knowledge object retention policy carries an unknown mode: workspace=%s", project_id)
        mode = RETENTION_MODE_REPORT_ONLY
    return RetentionPolicy(
        project_id=project_id,
        mode=mode,
        min_object_age_hours=int(row.min_object_age_hours),
        legal_hold=bool(row.legal_hold),
        explicit=True,
    )


async def load_retention_policy(db: AsyncSession, project_id: str) -> RetentionPolicy:
    if type(project_id) is not str or not project_id:
        raise InvalidRetentionRequestError()
    row = (
        await db.execute(
            select(KnowledgeObjectRetentionPolicy).where(
                KnowledgeObjectRetentionPolicy.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    return policy_from_row(project_id, row)


def _require_valid_policy_request(
    *,
    project_id: object,
    mode: object,
    min_object_age_hours: object,
    legal_hold: object,
    updated_by: object,
) -> None:
    if type(project_id) is not str or not project_id:
        raise InvalidRetentionRequestError()
    if type(mode) is not str or mode not in ALL_RETENTION_MODES:
        raise InvalidRetentionRequestError()
    if type(min_object_age_hours) is not int or not (
        MIN_OBJECT_AGE_HOURS <= min_object_age_hours <= MAX_OBJECT_AGE_HOURS
    ):
        raise InvalidRetentionRequestError()
    if type(legal_hold) is not bool:
        raise InvalidRetentionRequestError()
    if updated_by is not None and type(updated_by) is not str:
        raise InvalidRetentionRequestError()


async def set_retention_policy(
    db: AsyncSession,
    *,
    project_id: str,
    mode: object,
    min_object_age_hours: object = DEFAULT_MIN_OBJECT_AGE_HOURS,
    legal_hold: object = False,
    updated_by: str | None,
) -> RetentionPolicy:
    _require_valid_policy_request(
        project_id=project_id,
        mode=mode,
        min_object_age_hours=min_object_age_hours,
        legal_hold=legal_hold,
        updated_by=updated_by,
    )

    # The governance boundary, before the row is read: a policy change serializes with
    # reconciliation runs of the same Workspace.
    await lock_workspace_governance(db, project_id=project_id)
    row = (
        await db.execute(
            select(KnowledgeObjectRetentionPolicy).where(
                KnowledgeObjectRetentionPolicy.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = KnowledgeObjectRetentionPolicy(project_id=project_id)
        db.add(row)
    row.mode = mode
    row.min_object_age_hours = min_object_age_hours
    row.legal_hold = legal_hold
    row.updated_by = updated_by
    row.updated_at = utc_now()
    await db.commit()
    logger.info(
        "Knowledge object retention policy set: mode=%s legal_hold=%s age_hours=%d workspace=%s",
        mode,
        legal_hold,
        min_object_age_hours,
        project_id,
    )
    return RetentionPolicy(
        project_id=project_id,
        mode=mode,
        min_object_age_hours=min_object_age_hours,
        legal_hold=legal_hold,
        explicit=True,
    )
