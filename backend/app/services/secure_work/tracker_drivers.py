"""Tracker write-back drivers: one explicit contract per source system."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkItem
from ...models.runtime.secure_work import WorkItemWorkflowDefinition
from .jira.jira_state_sync import execute_jira_state_sync
from .platform_items import PLATFORM_SOURCE_TYPE
from .sync_policy import executes, load_item_intake

logger = logging.getLogger(__name__)


class TrackerStateSyncDriver(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        *,
        item: WorkItem,
        workflow: WorkItemWorkflowDefinition,
        preview: dict[str, Any],
    ) -> dict[str, Any] | None: ...


async def _local_only_driver(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    preview: dict[str, Any],
) -> dict[str, Any] | None:
    return None


TRACKER_STATE_SYNC_DRIVERS: dict[str, TrackerStateSyncDriver] = {
    "jira": execute_jira_state_sync,
    PLATFORM_SOURCE_TYPE: _local_only_driver,
}


def _source_driver(source_type: str) -> TrackerStateSyncDriver | None:
    from .intake.registry import source_for

    return getattr(source_for(source_type), "state_sync_driver", None)


async def execute_tracker_state_sync(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    preview: dict[str, Any],
) -> dict[str, Any] | None:
    # An explicit ``no_driver`` marker keeps the gap visible in the preview; the transition still applies locally.
    source_type = str(item.source_type or "").strip().lower()
    driver = TRACKER_STATE_SYNC_DRIVERS.get(source_type) or _source_driver(source_type)
    if driver is None:
        await load_item_intake(db, item)
        if not executes(getattr(workflow, "sync_policy_json", None), item):
            return None
        logger.warning(
            "tracker_state_sync.no_driver source_type=%s work_item=%s",
            source_type,
            item.source_key,
        )
        return {"status": "no_driver", "source_type": source_type}
    return await driver(db, item=item, workflow=workflow, preview=preview)


__all__ = [
    "TRACKER_STATE_SYNC_DRIVERS",
    "TrackerStateSyncDriver",
    "execute_tracker_state_sync",
]
