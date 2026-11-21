"""DB-only fixture and authority/allocator seams for handoff service boundary tests."""
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select

from app.models import (
    FlowDefinition,
    FlowDefinitionVersion,
    Session,
    WorkflowRun,
    WorkflowRunDecision,
    WorkflowRunSession,
)
from app.services.workflow_runs.handoff import service
from app.services.workflow_runs.handoff.contract import canonical_hash
from app.services.workflow_runs.phase_outputs import output_hash
from app.time_utils import utc_now
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_outsider, seed_workspace
from tests.work_role_support import assign_seed_role


async def setup_case(db, *, pool=False, deputy=None, detach=False):
    project = await seed_workspace(db)
    ids = [await seed_member(db, workspace_id=project, role=role) for role in ("admin", "viewer", "viewer")]
    sender, p, q = [await fetch_user(db, ident) for ident in ids]
    outsider = await fetch_user(db, await seed_outsider(db))
    flows = []
    for title in ("parent", "child"):
        flow = FlowDefinition(key=f"handoff-{title}-{uuid4()}", name=title, project_id=project,
                              status="published", created_by=sender.id)
        db.add(flow)
        await db.flush()
        version = FlowDefinitionVersion(flow_id=flow.id, status="published", created_by=sender.id,
            definition_json={"execution_kind": "phased", **({"nodes": [
                {"id": "start", "type": "start"},
                {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
                "edges": [{"id": "start-done", "source_node_id": "start", "target_node_id": "done"}]}
                if title == "child" else {})})
        db.add(version)
        await db.flush()
        flow.current_version_id = version.id
        flows.append((flow, version))
    body = {"type": "task", "summary": "Controlled task", "repository": "bitbucket:demo-team/test",
            "acceptance_criteria": ["Inspect the task"], "complete": True}
    envelope = {"kind": "definition_of_ready", "version": 1, "hash": output_hash(body), "record": body,
                "node_id": "draft", "entry": 1}
    parent = WorkflowRun(project_id=project, workflow_kind="phased", workflow_key=flows[0][0].key,
        flow_definition_version_id=flows[0][1].id, requested_by=sender.id, current_node_id="offer", status="running",
        state_version=7, repository="bitbucket:demo-team/test", node_state={"entry": 4},
        context={"outputs": {"definition_of_ready": envelope}, "sender_transcript": "SENDER_ONLY_CANARY"})
    db.add(parent)
    await db.flush()
    payload = {"subject": "advance", "shows": "definition_of_ready", "output": {"version": 1,
               "hash": envelope["hash"], **body}}
    decision = WorkflowRunDecision(run_id=parent.id, kind="confirmation", subject="advance", action="confirmed",
        decided_by=sender.id, payload=payload, payload_hash=output_hash(payload), created_at=utc_now())
    db.add(decision)
    if pool or deputy:
        for actor in (p, q):
            await assign_seed_role(db, project, "doc_owner", user_id=actor.id)
    await db.flush()
    contract = {"schema_version": "handoff/v1", "owner": "role:doc_owner" if pool else f"person:{p.id}",
        "artefacts": ["definition_of_ready"], "acceptance": "Inspect the task",
        "scope": {"workspace_id": project, "work_item_id": None, "repository": parent.repository,
                  "service_ids": [], "connection_ids": [], "source_ids": []},
        "detach": detach, "timeout_seconds": 300, "deputy": deputy}
    row = await service.offer_handoff(db, parent, node_id="offer", contract=contract,
        child_descriptor={"workflow_key": flows[1][0].key, "version_id": flows[1][1].id})
    await db.flush()
    return SimpleNamespace(parent=parent, row=row, sender=sender, p=p, q=q, outsider=outsider, decision=decision)


async def rights(**kwargs):
    return {"allowed": True, "actor_id": kwargs["actor"].id,
        "scope_digest": canonical_hash({"scope": kwargs["scope"], "envelopes": kwargs["envelopes"]}),
        "runtime_target": kwargs["runtime_target"]}


async def allocate(*, db, parent, handoff, actor, runtime_proof):
    child = WorkflowRun(project_id=handoff.workspace_id, workflow_kind="phased",
        workflow_key=handoff.child_descriptor["workflow_key"], requested_by=actor.id,
        flow_definition_version_id=handoff.child_descriptor["version_id"], parent_run_id=parent.id,
        parent_node_id=handoff.parent_node_id, repository=handoff.contract["scope"]["repository"], status="waiting",
        context={"runtime_target": runtime_proof["runtime_target"]}, node_state={"entry": 0})
    session = Session(user_id=actor.id, project_id=handoff.workspace_id)
    db.add_all([child, session])
    await db.flush()
    db.add(WorkflowRunSession(run_id=child.id, session_id=session.id, role="main", runtime="chat", active=True))
    await db.flush()
    return {"child_run_id": child.id, "receiver_session_id": session.id}


def action(row, kind="accept"):
    return {"action": kind, "payload_hash": row.payload_hash, "round": row.round,
        "expected_state_version": row.state_version,
        **({"runtime_target": {"kind": "server"}} if kind == "accept" else {"reason": "Unavailable this round"})}


async def counts(db):
    return tuple([(await db.execute(select(func.count()).select_from(model))).scalar_one()
                  for model in (WorkflowRun, Session)])
