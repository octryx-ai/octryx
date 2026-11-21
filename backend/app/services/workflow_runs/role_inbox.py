"""Personal decision offers; work roles never grant access to the requester's thread."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ..secure_work.access import work_scope_project_ids
from .decider import resolve_decider
from .graph import graph_for_run
from .hitl_actions import decision_actions


async def inbox_items(db: AsyncSession, user: User) -> list[dict]:
    scope = await work_scope_project_ids(db, user)
    if scope == set():
        return []
    query = select(WorkflowRun).where(WorkflowRun.status == "waiting")
    if scope is not None:
        query = query.where(WorkflowRun.project_id.in_(scope))
    rows = (await db.execute(query.order_by(WorkflowRun.updated_at.desc()).limit(100))).scalars().all()
    items = []
    for run in rows:
        node = (await graph_for_run(db, run)).nodes.get(str(run.current_node_id or ""))
        if node is None or "decider" not in node.config:
            continue
        resolution = await resolve_decider(db, run, node)
        if not resolution.allows(user.id) or not await decision_actions(db, run, user=user):
            continue
        items.append({"kind": "workflow_run_role_decision", "id": run.id,
            "title": f"Decide: {run.title}", "created_at": run.updated_at.isoformat() if run.updated_at else None,
            "subtitle": f"Current decision · {resolution.policy}", "decision_action": {"run_id": run.id},
            "link": {"label": "Open this decision"}})
    return items
