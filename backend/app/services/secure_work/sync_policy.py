"""Source-neutral names of a workflow's write-back settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key

from ...models import WorkItem, WorkItemSyncConfig

SYNC_MODE_EXECUTE = "execute"
SYNC_MODE_DRY_RUN = "dry_run_only"
SYNC_MODES = (SYNC_MODE_DRY_RUN, SYNC_MODE_EXECUTE)
SOURCE_SYNC_MODE_KEY = "sync_mode"
STATUS_KEY = "source_status"
TRANSITION_KEY = "source_transition"


def _value(entry: Any, key: str) -> Any:
    value = entry.get(key) if isinstance(entry, Mapping) else None
    return None if value in (None, "") else value


def sync_mode(policy: Any) -> str:
    return str(_value(policy, SOURCE_SYNC_MODE_KEY) or "").strip()


def intake_sync_mode(options: Any) -> str:
    # The save API only stores ``SYNC_MODES``, so an unknown stored value is no mode and the workflow default applies.
    mode = str(options.get(SOURCE_SYNC_MODE_KEY) or "").strip() if isinstance(options, Mapping) else ""
    return mode if mode in SYNC_MODES else ""


def _loaded_intake(item: Any) -> Any:
    # The gates are synchronous, so the row must already be in the session: ``load_item_intake`` attaches it at every
    # async entry point.
    config_id = getattr(item, "sync_config_id", None)
    if not config_id:
        return None
    try:
        state = inspect(item)
    except NoInspectionAvailable:
        return getattr(item, "sync_config", None)
    if "sync_config" in state.dict:
        return state.dict["sync_config"]
    if state.session is None:
        return None
    return state.session.identity_map.get(identity_key(WorkItemSyncConfig, config_id))


async def load_item_intake(db: AsyncSession, item: Any) -> None:
    # The synchronous gates must see the intake's own ``sync_mode``.
    config_id = getattr(item, "sync_config_id", None)
    if config_id and isinstance(db, AsyncSession) and isinstance(item, WorkItem):
        intake = await db.get(WorkItemSyncConfig, config_id)
        if intake is not None:
            # Held on the item: the session's identity map is weak and would drop an unreferenced row again.
            set_committed_value(item, "sync_config", intake)


def item_sync_mode(item: Any) -> str:
    intake = _loaded_intake(item)
    return intake_sync_mode(getattr(intake, "sync_options_json", None)) if intake is not None else ""


def effective_sync_mode(policy: Any, item: Any = None, *, source_mode: str = "") -> str:
    return source_mode or (item_sync_mode(item) if item is not None else "") or sync_mode(policy)


def executes(policy: Any, item: Any = None, *, source_mode: str = "") -> bool:
    return effective_sync_mode(policy, item, source_mode=source_mode) == SYNC_MODE_EXECUTE


def mapped_status(entry: Any) -> Any:
    return _value(entry, STATUS_KEY)


def mapped_transition(entry: Any) -> Any:
    return _value(entry, TRANSITION_KEY)


__all__ = [
    "SOURCE_SYNC_MODE_KEY",
    "STATUS_KEY",
    "SYNC_MODES",
    "SYNC_MODE_DRY_RUN",
    "SYNC_MODE_EXECUTE",
    "TRANSITION_KEY",
    "effective_sync_mode",
    "executes",
    "intake_sync_mode",
    "item_sync_mode",
    "load_item_intake",
    "mapped_status",
    "mapped_transition",
    "sync_mode",
]
