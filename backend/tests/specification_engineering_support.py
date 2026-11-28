"""Actual accepted-spec engineering child on the NEW authored B graph, for SQLite and PostgreSQL tests."""
from __future__ import annotations

import copy
import uuid

from sqlalchemy import select

from app.models import FlowDefinition, FlowDefinitionVersion, WorkflowRun, WorkflowRunDecision
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.allocation import allocate_child
from app.services.workflow_runs.handoff.permissions import rights_evaluator
from tests.phased_workflow_fixtures import publish_phased
from tests.specification_engineering_graph_support import ENGINEERING_KEY, spec_engineering_definition
from tests.team_handoff_support import action

SPEC_CRITERIA = [
    {"id": "AC7", "story_ids": ["ST1"], "given": "An admitted source", "when": "I view the claim",
     "then": "I can inspect its exact evidence"},
    {"id": "AC2", "story_ids": ["ST1"], "given": "An unavailable source", "when": "I request its content",
     "then": "Its protected content stays withheld"},
]


async def spec_decision(db, parent) -> WorkflowRunDecision:
    rows = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == parent.id,
        WorkflowRunDecision.kind == "confirmation").order_by(WorkflowRunDecision.created_at.desc()))).scalars().all()
    return next(row for row in rows if dict(row.payload or {}).get("shows") == "spec")


async def engineering_child_case(db, *, criteria=None, runtime_target=None):
    from tests.test_specification_handoff_authority import offer, prepared_spec_case

    # The PM's and a denied viewer's source access are fixed before the brief freezes its ACL snapshot.
    case = await prepared_spec_case(db, criteria=copy.deepcopy(criteria or SPEC_CRITERIA), members=(True, False))
    case.pm, case.denied = case.members
    # The PM confirmed the exact spec; the producer (parent requester) confirmed only the idea and the plan.
    (await spec_decision(db, case.parent)).decided_by = case.pm.id
    await db.flush()
    key = await publish_phased(db, spec_engineering_definition(), key=f"{ENGINEERING_KEY}-{uuid.uuid4().hex[:8]}")
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == key))).scalar_one()
    case.version = await db.get(FlowDefinitionVersion, flow.current_version_id)
    case.descriptor = {"workflow_key": key, "version_id": flow.current_version_id}
    await offer(db, case)
    accept = action(case.row)
    if runtime_target is not None:
        accept["runtime_target"] = dict(runtime_target)
    case.binding = await service.accept_handoff(db, case.row.id, case.receiver, accept,
                                               rights_evaluator=rights_evaluator, allocator=allocate_child)
    case.child = await db.get(WorkflowRun, case.binding["child_run_id"])
    case.engineer = case.receiver
    await db.commit()
    return case


async def enter_node(db, child, node_id: str) -> None:
    from app.services.workflow_runs.engine import restart_at

    await restart_at(db, child, node_id, actor_id=None)
    await db.commit()


__all__ = ["SPEC_CRITERIA", "engineering_child_case", "enter_node", "spec_decision"]
