"""What a device needs to build the context pack for a run's writing phase (the offer's ``context_pack``); the
launcher builds the pack from its checkout, without a model, and puts it in front of the phase's first prompt."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

READ_ONLY = "read_only"
MAX_DESCRIPTION = 8000  # only matched against, never shown: the pack itself has its own cap
MAX_PATHS = 30
_FILE = re.compile(r"(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,8}")


async def _item_phase(db: AsyncSession, run: Any, session_id: str | None) -> tuple[Any, dict[str, Any]] | None:
    from ....models import Session
    from ..graph import graph_for_run
    from ..teamwork import work_of
    from ..teamwork.item_sessions import item_idle_reason, item_phase_node, session_item

    session = await db.get(Session, session_id) if session_id else None
    item = session_item(run, session) if session is not None else None
    work_node = (await graph_for_run(db, run)).nodes.get(str(work_of(run).get("node_id") or "")) if item else None
    if item is None or work_node is None or item_idle_reason(run, session) is not None:
        return None
    # A teamwork item's session works under its item's phase (``contract._session_node``), on its own text and paths.
    return item_phase_node(run, work_node, item), {"key": str(item.get("id") or ""),
                                                   "title": str(item.get("title") or ""),
                                                   "description": str(item.get("instructions") or ""),
                                                   "paths": [str(path) for path in item.get("paths") or []]}


# The files a red pipeline (failed tests, code style findings) or a review names: the next pass works on them.
def _named_paths(contract: dict[str, Any]) -> list[str]:
    facts = dict(contract.get("workflow_run_phase") or {})
    named = json.dumps([facts.get("pipeline_failure"), facts.get("review_findings")], default=str)
    return list(dict.fromkeys(_FILE.findall(named)))


async def context_pack_request(db: AsyncSession, run: Any, phase: Any,
                               session_id: str | None = None) -> dict[str, Any] | None:
    from ....models.runtime.secure_work import WorkItem
    from ..phase_contract import phase_definition
    from ..workspace.contract_pin import view

    if run is None:
        return None
    teamwork = await _item_phase(db, run, session_id)
    if teamwork is not None:
        phase, item = teamwork
    else:
        found = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
        item = {"key": str(found.source_key or ""), "title": str(found.title or ""),
                "description": str(found.description or "")} if found is not None else None
    if phase is None or item is None:
        return None
    contract = dict(phase_definition(run, phase).get("workflow_contract") or {})
    # An item always writes in its own worktree; its synthetic phase names no capability class.
    if teamwork is None and str(contract.get("capability_class") or READ_ONLY) == READ_ONLY:
        return None
    environment = dict(dict(view(run) or {}).get("environment") or {})
    paths = list(dict.fromkeys([*item.get("paths", []), *_named_paths(contract)]))[:MAX_PATHS]
    return {"phase": f"{phase.id}:{item['key']}" if teamwork else str(phase.id),
            "app_folder": str(environment.get("app_folder") or "."),
            "item": {**item, "description": item["description"][:MAX_DESCRIPTION], "paths": paths}}


__all__ = ["context_pack_request"]
