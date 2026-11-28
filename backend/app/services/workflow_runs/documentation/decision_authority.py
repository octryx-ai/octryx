"""Revalidate the human authority of the original publication confirmation."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun, WorkflowRunDecision
from ..decider import resolve_decider
from ..graph import CONFIRMED, NODE_CONFIRMATION, SUBJECT_PUBLICATION, graph_for_run
from ..pause import payload_hash
from ..work_roles import active_human, lock_actor_membership


async def publication_decision_problem(db: AsyncSession, run: WorkflowRun,
                                       decision: WorkflowRunDecision | None) -> str:
    if decision is None:
        return "the publication decision does not exist"
    stored = await db.get(WorkflowRunDecision, decision.id, populate_existing=True)
    if (stored is None or stored.run_id != run.id or stored.kind != "confirmation"
            or stored.subject != SUBJECT_PUBLICATION or stored.action != CONFIRMED):
        return "the decision is not this run's confirmed publication"
    if not stored.payload_hash or payload_hash(stored.payload) != stored.payload_hash:
        return "the confirmed target and body do not bind their card hash"
    from ..handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    binding = (await db.execute(select(WorkflowRun.project_id, WorkflowRun.requested_by,
        WorkflowRun.flow_definition_version_id).where(WorkflowRun.id == run.id).with_for_update())).one_or_none()
    if binding is None or tuple(binding) != (run.project_id, run.requested_by, run.flow_definition_version_id):
        return "the run's publication authority binding changed"
    node = (await graph_for_run(db, run)).nodes.get(str(stored.node_id or ""))
    if node is None or node.kind != NODE_CONFIRMATION or node.config.get("subject") != SUBJECT_PUBLICATION:
        return "the approving publication node is not in the run's pinned graph"
    actor = await active_human(db, str(stored.decided_by or ""))
    if actor is None:
        return "the publication confirmer is not a current active human"
    resolution = await resolve_decider(db, run, node)
    if not resolution.allows(actor.id):
        return "the publication confirmer no longer has the approving node's authority"
    await lock_actor_membership(db, run.project_id, actor.id,
        role_key=resolution.policy[5:] if resolution.policy.startswith("role:") else None)
    actor = await active_human(db, actor.id)
    resolution = await resolve_decider(db, run, node)
    if actor is None or not resolution.allows(actor.id):
        return "the publication confirmer's authority changed before publication"
    from ..specification.lineage import SpecificationUnavailable
    from ..specification.origin import spec_bound, viewer_spec

    if await spec_bound(db, run):
        try:
            # A spec-bound page quotes the accepted spec: the confirmer's own current source authority.
            await viewer_spec(db, run, actor)
        except SpecificationUnavailable:
            return "the publication confirmer's access to the accepted specification's sources changed"
    return ""
