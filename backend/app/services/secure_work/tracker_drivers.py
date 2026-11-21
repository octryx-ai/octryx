"""Tracker write-back drivers: one explicit contract per source system.

The WorkItem model is source-agnostic (``source_type``/``source_instance``/
``source_key``); this module makes the write-back side match. A driver owns
the outbound state-sync operation for one source type, and resolution is
explicit — platform items are local-only by definition, an unmapped source
type is a visible ``no_driver`` result, never a silent guess. Adding a new
tracker (ServiceNow, GitHub, ...) means registering one driver here, or giving
the Work source in ``intake/registry`` a ``state_sync_driver`` (a source brings
its write-back with it); the workflow layer stays untouched.
"""

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
    """Platform-native items: state lives here, there is nothing to sync."""
    return None


TRACKER_STATE_SYNC_DRIVERS: dict[str, TrackerStateSyncDriver] = {
    "jira": execute_jira_state_sync,
    PLATFORM_SOURCE_TYPE: _local_only_driver,
}


def _source_driver(source_type: str) -> TrackerStateSyncDriver | None:
    """The write-back a registered Work source brings (``state_sync_driver``), if any."""
    from .intake.registry import source_for

    return getattr(source_for(source_type), "state_sync_driver", None)


async def execute_tracker_state_sync(
    db: AsyncSession,
    *,
    item: WorkItem,
    workflow: WorkItemWorkflowDefinition,
    preview: dict[str, Any],
) -> dict[str, Any] | None:
    """Dispatch the write-back to the item's source-type driver.

    Returns the driver's execution result, None when the transition stays
    local, or an explicit ``no_driver`` marker for source types without a
    registered driver — the transition still applies locally, but the gap
    is visible in the preview instead of silently swallowed. The gap only
    exists where write-back is on: an intake whose own ``sync_mode`` (else the
    workflow's) is not ``execute`` wants nothing written, so it stays local
    (``sync_policy``).
    """
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
