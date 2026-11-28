"""The background workers' periodic reconciliation of every Workspace with a retention policy. Each Workspace's outcome,
a failure included, is its recorded run."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from collections.abc import Callable, Mapping

from sqlalchemy import select

from ....config import get_settings
from ....models.project.knowledge_object_retention import (
    RETENTION_FAILURE_CONTRACT,
    KnowledgeObjectRetentionPolicy,
)
from ....time_utils import utc_now
from ...background_worker_state import (
    record_background_worker_failure,
    record_background_worker_partial,
    record_background_worker_success,
)
from ...data_access import platform_maintenance
from ..objects import KnowledgeObjectError, KnowledgeObjectMaintenance, object_store_config_from_mapping
from .errors import RetentionError
from .failures import failure_token
from .reconcile import reconcile_workspace, record_failed_run

logger = logging.getLogger(__name__)

RECONCILE_REASON = "knowledge retention reconcile: inventory the objects of every Workspace with a retention policy"
REQUESTED_BY = "job:retention-reconcile"
WORKER_NAME = "knowledge_retention_reconcile_worker"
# The reconciliation identity's shared-credentials profile: it holds the list grant the application identity lacks.
ENV_RECONCILE_AWS_PROFILE = "OCTRYX_KNOWLEDGE_RECONCILE_AWS_PROFILE"

MaintenanceFactory = Callable[[], KnowledgeObjectMaintenance]


def maintenance_from_environment(environ: Mapping[str, str] | None = None) -> KnowledgeObjectMaintenance:
    environ = os.environ if environ is None else environ
    config = object_store_config_from_mapping(environ)
    profile = environ.get(ENV_RECONCILE_AWS_PROFILE)
    if profile:
        config = dataclasses.replace(config, credentials_profile=profile)
    return KnowledgeObjectMaintenance(config)


# The Workspace outcome counts of one pass; store_failure is the failure token of an unusable object store.
@dataclasses.dataclass(frozen=True)
class ReconcilePass:
    counts: dict[str, int]
    store_failure: str = ""

    @property
    def all_failed(self) -> bool:
        return self.counts["workspaces"] > 0 and self.counts["failed"] == self.counts["workspaces"]


async def reconcile_every_workspace(
    session_factory, *, maintenance_factory: MaintenanceFactory = maintenance_from_environment
) -> ReconcilePass:
    outcome = {"workspaces": 0, "reconciled": 0, "failed": 0}
    async with platform_maintenance(RECONCILE_REASON), session_factory() as db:
        project_ids = list(
            (
                await db.execute(
                    select(KnowledgeObjectRetentionPolicy.project_id).order_by(
                        KnowledgeObjectRetentionPolicy.project_id
                    )
                )
            ).scalars()
        )
        if not project_ids:
            return ReconcilePass(outcome)
        maintenance: KnowledgeObjectMaintenance | None = None
        unusable_store = ""
        try:
            maintenance = maintenance_factory()
        except KnowledgeObjectError as error:
            unusable_store = failure_token(error)
        for project_id in project_ids:
            outcome["workspaces"] += 1
            if maintenance is None:
                await record_failed_run(db, project_id=project_id, requested_by=REQUESTED_BY, failure=unusable_store)
                reconciled = False
            else:
                reconciled = await _reconcile_one(db, maintenance, project_id)
            outcome["reconciled" if reconciled else "failed"] += 1
    return ReconcilePass(outcome, unusable_store)


async def _reconcile_one(db, maintenance: KnowledgeObjectMaintenance, project_id: str) -> bool:
    try:
        await reconcile_workspace(db, maintenance=maintenance, project_id=project_id, requested_by=REQUESTED_BY)
    except RetentionError as error:
        # reconcile_workspace recorded the failed run before raising.
        logger.warning("Knowledge retention reconcile failed: state=%s workspace=%s", error.state.value, project_id)
        return False
    except Exception:
        await db.rollback()
        logger.exception("Knowledge retention reconcile crashed: workspace=%s", project_id)
        await record_failed_run(
            db, project_id=project_id, requested_by=REQUESTED_BY, failure=RETENTION_FAILURE_CONTRACT
        )
        return False
    return True


class KnowledgeRetentionReconcileWorker:
    def __init__(
        self,
        session_factory,
        *,
        maintenance_factory: MaintenanceFactory = maintenance_from_environment,
        interval_seconds: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._maintenance_factory = maintenance_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="knowledge-retention-reconcile")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run_once(self) -> dict[str, int]:
        started_at = utc_now()
        try:
            reconciled = await reconcile_every_workspace(
                self._session_factory, maintenance_factory=self._maintenance_factory
            )
        except Exception as error:
            await record_background_worker_failure(
                self._session_factory, worker_name=WORKER_NAME, owner="knowledge", started_at=started_at, error=error
            )
            raise
        outcome = reconciled.counts
        if reconciled.all_failed:
            # The store's own token keeps "no knowledge store set up" apart from a store that fails.
            failure = reconciled.store_failure or (
                f"every Workspace failed reconciliation ({outcome['failed']} of {outcome['workspaces']})"
            )
            await record_background_worker_failure(
                self._session_factory, worker_name=WORKER_NAME, owner="knowledge", started_at=started_at,
                error=failure,
            )
        elif outcome["failed"]:
            await record_background_worker_partial(
                self._session_factory, worker_name=WORKER_NAME, owner="knowledge", started_at=started_at,
                result=outcome, error="some Workspaces failed reconciliation",
            )
        else:
            await record_background_worker_success(
                self._session_factory, worker_name=WORKER_NAME, owner="knowledge", started_at=started_at,
                result=outcome,
            )
        return outcome

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Knowledge retention reconcile pass failed")
            await asyncio.sleep(self._interval())

    def _interval(self) -> int:
        if self._interval_seconds is not None:
            return self._interval_seconds
        return get_settings().knowledge_retention_reconcile_interval_hours * 3600


__all__ = [
    "ENV_RECONCILE_AWS_PROFILE",
    "RECONCILE_REASON",
    "REQUESTED_BY",
    "KnowledgeRetentionReconcileWorker",
    "ReconcilePass",
    "maintenance_from_environment",
    "reconcile_every_workspace",
]
