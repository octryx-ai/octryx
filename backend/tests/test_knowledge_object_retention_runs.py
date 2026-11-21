"""Reconciliation run timing, supersession of earlier observations, failed runs and operator identity validation."""

from __future__ import annotations

from datetime import timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.project.knowledge_object_retention import (
    FINDING_STATE_OBSERVED,
    FINDING_STATE_SUPERSEDED,
    RETENTION_FAILURE_UNAUTHORIZED,
    RUN_STATE_FAILED,
    KnowledgeObjectReconciliationFinding,
    KnowledgeObjectReconciliationRun,
)
from app.services.knowledge.retention.errors import (
    InvalidRetentionRequestError,
    RetentionRecordNotFoundError,
    RetentionUnauthorizedError,
)
from app.services.knowledge.retention.reconcile import reconcile_workspace
from app.time_utils import utc_now, utc_now_aware
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.knowledge_object_retention_support import OPERATOR, _abandon, _authorized, _set_policy, _wired


async def test_the_age_clock_is_timezone_aware_and_needs_no_injected_clock(db):
    """Age eligibility decides whether bytes may be deleted, so its instant must be explicit.

    The default clock is aware (``utc_now_aware``), an injected clock must be aware too, and
    an offset-naive value is refused rather than assumed to be UTC. The same instant expressed
    in another zone must produce the same age, which is the property that makes the aware
    contract worth having.
    """
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    await _abandon(runtime, client, authorized, age_hours=200)

    # No clock injected at all: the default is aware and the run completes.
    default_run = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )
    assert default_run.findings[0].observed_age_hours == 200

    # An offset-naive instant is an invalid request, not an implicit UTC value.
    with pytest.raises(InvalidRetentionRequestError):
        await reconcile_workspace(
            db,
            maintenance=maintain,
            project_id=workspace_id,
            requested_by=OPERATOR,
            now=utc_now(),
        )

    # The same instant in another zone is the same instant, so the age is unchanged.
    tokyo = utc_now_aware().astimezone(timezone(timedelta(hours=9)))
    shifted = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR, now=tokyo
    )
    assert shifted.findings[0].observed_age_hours == 200


async def test_a_new_run_supersedes_earlier_observations(db):
    workspace_id = await seed_workspace(db)
    authorized = await _authorized(db, workspace_id)
    runtime, maintain, client = _wired()
    await _abandon(runtime, client, authorized, age_hours=200)
    await _set_policy(db, workspace_id)
    first = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )

    second = await reconcile_workspace(
        db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR
    )

    assert second.run_id != first.run_id
    stale = await db.get(KnowledgeObjectReconciliationFinding, first.findings[0].finding_id)
    assert stale.state == FINDING_STATE_SUPERSEDED
    # Only the newest run's own finding is ``observed``.
    states = (
        (
            await db.execute(
                select(KnowledgeObjectReconciliationFinding.state).where(
                    KnowledgeObjectReconciliationFinding.project_id == workspace_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(states) == [FINDING_STATE_OBSERVED, FINDING_STATE_SUPERSEDED]



async def test_an_inventory_failure_is_recorded_as_a_failed_run_with_a_fixed_token(db):
    workspace_id = await seed_workspace(db)
    runtime, maintain, client = _wired()
    assert runtime is not None
    client.unauthorized = True

    with pytest.raises(RetentionUnauthorizedError) as failure:
        await reconcile_workspace(db, maintenance=maintain, project_id=workspace_id, requested_by=OPERATOR)

    run = (
        await db.execute(
            select(KnowledgeObjectReconciliationRun).where(
                KnowledgeObjectReconciliationRun.project_id == workspace_id
            )
        )
    ).scalar_one()
    assert run.state == RUN_STATE_FAILED and run.failure == RETENTION_FAILURE_UNAUTHORIZED
    rendered = f"{failure.value} {failure.value.state.value}"
    assert "server text" not in rendered and "AccessDenied" not in rendered
    assert failure.value.__cause__ is None and failure.value.__context__ is None


async def test_an_unknown_workspace_is_not_found(db):
    _, maintain, _ = _wired()
    with pytest.raises(RetentionRecordNotFoundError):
        await reconcile_workspace(
            db,
            maintenance=maintain,
            project_id="11111111-2222-3333-4444-555555555555",
            requested_by=OPERATOR,
        )
    with pytest.raises(InvalidRetentionRequestError):
        await reconcile_workspace(db, maintenance=maintain, project_id="not-a-uuid", requested_by=OPERATOR)


async def test_the_operator_identity_token_is_validated(db):
    workspace_id = await seed_workspace(db)
    _, maintain, _ = _wired()
    for operator in ("", "cli:", "no-scheme", "cli:" + "a" * 80, "cli:semi;colon"):
        with pytest.raises(InvalidRetentionRequestError):
            await reconcile_workspace(
                db, maintenance=maintain, project_id=workspace_id, requested_by=operator
            )
