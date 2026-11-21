"""The documentation grant of unattended epic documentation (see ``auto_pages``): own, inherited or recorded now."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ....models.runtime.secure_work import WorkItem
from ....time_utils import utc_now
from ...project.service import get_project_config
from ..records import record_event
from .page import SETTINGS_KEY, DocumentationSettings, documentation_settings

AUTO_PUBLISH = "auto_publish"
GRANT_KEY = "documentation_grant"
EVENT_GRANT = "documentation_grant_recorded"
BINDING = ("workspace_id", "space_key", "parent_page_id", "connection_id", "instance")
OPERATIONS = ("create_under_parent", "update_own_pages")
MAX_CHAIN = 100


def auto_publish(project_config: dict[str, Any] | None) -> bool:
    return dict((project_config or {}).get(SETTINGS_KEY) or {}).get(AUTO_PUBLISH) is True


class _StopError(Exception):
    """The step ends here: ``reason`` is the skip's (``failed``: a Confluence error)."""

    def __init__(self, reason: str, detail: dict[str, Any] | None = None, *, failed: bool = False) -> None:
        super().__init__(reason)
        self.reason, self.detail, self.failed = reason, dict(detail or {}), failed


async def _epic(db: AsyncSession, run: WorkflowRun) -> tuple[WorkItem | None, WorkItem | None]:
    """``(epic, story)``: the spec run's own epic, or a story run's story and its epic."""
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return None, None
    if str(item.issue_type or "").lower() == "epic":
        return item, None
    if not item.epic_key:
        return None, item
    epic = (await db.execute(select(WorkItem).where(
        WorkItem.source_key == item.epic_key, WorkItem.project_id == run.project_id).limit(1))).scalar_one_or_none()
    return epic, item


async def _inherited(db: AsyncSession, run: WorkflowRun, epic_key: str) -> dict[str, Any] | None:
    """The grant of the run this story builds on (``epic_chain.after_run``, followed back), for the same epic."""
    from ..epic_chain import CHAIN_KEY

    seen: set[str] = {run.id}
    after = str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    for _ in range(MAX_CHAIN):
        if not after or after in seen:
            return None
        seen.add(after)
        earlier = await db.get(WorkflowRun, after)
        if earlier is None or earlier.project_id != run.project_id:
            return None
        grant = dict(earlier.context or {}).get(GRANT_KEY)
        if isinstance(grant, dict) and grant.get("epic") == epic_key:
            return grant
        after = str(dict(dict(earlier.context or {}).get(CHAIN_KEY) or {}).get("after_run") or "")
    return None


async def _current_target(db: AsyncSession, run: WorkflowRun, settings: DocumentationSettings) -> dict[str, str]:
    """Where the Workspace points now (the one resolver for the connection), else :class:`_StopError`."""
    from .target import ConnectionUnavailableError, _space_allowed, served_confluence

    if not settings.parent_page_id:
        raise _StopError("no_parent_page")  # a grant covers one subtree, never the space root
    try:
        served = await served_confluence(db, run, settings.space_key)
    except ConnectionUnavailableError as error:
        raise _StopError("no_confluence_connection", {"code": error.code}) from None
    if not _space_allowed(served.config, settings.space_key):
        raise _StopError("space_not_allowed", {"space_key": settings.space_key, "connection": served.name})
    return {"workspace_id": str(run.project_id or ""), "space_key": settings.space_key,
            "parent_page_id": settings.parent_page_id, "connection_id": served.connection_id,
            "connection_name": served.name, "instance": served.instance}


def _drift(granted: dict[str, Any], current: dict[str, Any], keys: tuple[str, ...] = BINDING) -> list[str]:
    return [f"{key}: {granted.get(key)!r} -> {current.get(key)!r}" for key in keys
            if (granted.get(key) or None) != (current.get(key) or None)]


async def _grant(db: AsyncSession, run: WorkflowRun) -> tuple[dict[str, Any], WorkItem | None, WorkItem | None]:
    """The run's documentation grant (own, inherited or recorded now), or :class:`_StopError` (a skip)."""
    config = await get_project_config(run.project_id, db)
    settings = documentation_settings(config)
    if settings is None:
        raise _StopError("no_documentation_space")
    if not auto_publish(config):
        raise _StopError("auto_publish_off")
    epic, story = await _epic(db, run)
    epic_key = str(epic.source_key) if epic is not None else ""
    own = dict(run.context or {}).get(GRANT_KEY)
    # A copy: the earlier run's recorded grant stays as it was; this run records its own (with its pages).
    grant = copy.deepcopy(own if isinstance(own, dict) else await _inherited(db, run, epic_key))
    if grant is not None:
        # The configuration first: a changed space or parent is drift before anything is resolved or read.
        drift = _drift(dict(grant.get("target") or {}), {"space_key": settings.space_key,
                                                         "parent_page_id": settings.parent_page_id},
                       ("space_key", "parent_page_id"))
        if drift:
            raise _StopError("target_drift", {"drift": drift, "grant_id": grant.get("id")})
    current = await _current_target(db, run, settings)
    if grant is None:
        grant = {"id": uuid.uuid4().hex, "epic": epic_key, "granted_by": run.requested_by, "run_id": run.id,
                 "granted_at": utc_now().isoformat(), "basis": f"{SETTINGS_KEY}.{AUTO_PUBLISH}",
                 "operations": list(OPERATIONS), "target": current, "pages": {}}
        record_event(db, run, EVENT_GRANT, node_id=run.current_node_id, detail={
            "grant_id": grant["id"], "epic": epic_key, "operations": list(OPERATIONS),
            **{key: current[key] for key in BINDING}})
    else:
        drift = _drift(dict(grant.get("target") or {}), current)
        if drift:
            raise _StopError("target_drift", {"drift": drift, "grant_id": grant.get("id")})
        if not isinstance(own, dict):
            record_event(db, run, EVENT_GRANT, node_id=run.current_node_id, detail={
                "grant_id": grant.get("id"), "epic": epic_key, "inherited_from": grant.get("run_id")})
    _keep(run, grant)
    return grant, epic, story


def _keep(run: WorkflowRun, grant: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), GRANT_KEY: grant}
