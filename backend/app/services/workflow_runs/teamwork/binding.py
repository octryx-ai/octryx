"""An item session's turn is governed by its item's synthetic phase."""

from __future__ import annotations

from typing import Any

from ..binding import held_resolution, phase_resolution
from ..graph import NODE_PARALLEL, graph_for_run
from ..states import RUN_RESOLUTION_KEY, STATUS_RUNNING
from . import RUNNING, item_key_of, session_works_on, work_of


async def item_turn_resolution(db: Any, run: Any, session: Any) -> dict[str, Any]:
    key = item_key_of(session) or ""
    work = work_of(run)
    item = dict(dict(work.get("items") or {}).get(key) or {})
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id or "")
    if (run.status != STATUS_RUNNING or node is None or node.kind != NODE_PARALLEL or work.get("node_id") != node.id
            or item.get("status") != RUNNING or not session_works_on(run, item, session)):
        return held_resolution(run, profile_status="needs_clarification",
                               reason=f"Item '{key}' of the workflow run is not running.")
    from ..phase_agent_binding import bind_phase_agent
    from .item_definition import item_definition, item_node

    definition = item_definition(run, node, item)
    resolution = phase_resolution(run=run, node_id=node.id, definition=definition)
    resolution = await bind_phase_agent(db, run, item_node(run, node, item), resolution)
    if isinstance(resolution.get(RUN_RESOLUTION_KEY), dict) and resolution.get("status") == "matched":
        resolution[RUN_RESOLUTION_KEY] = {**resolution[RUN_RESOLUTION_KEY], "item": key}
    return resolution


__all__ = ["item_turn_resolution"]
