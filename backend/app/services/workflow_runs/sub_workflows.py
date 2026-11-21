"""A sub-workflow node: the run starts another published workflow and routes on its outcome.

The child run is linked to its parent (``parent_run_id``, ``parent_node_id``) and takes over the parent's
chat session while it runs; when it ends the session returns to the parent and the parent continues on the
child's outcome (a failed child counts as ``blocked``). Nesting is bounded (at most
``MAX_SUB_WORKFLOW_DEPTH`` runs deep) and a workflow never starts itself again (A → A, A → B → A). The node's
``handoff`` names recorded outputs the child receives (E hands its incident hypothesis to C's phases).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, User, WorkflowRun
from .graph import PhasedNode
from .records import bind_session, lock_run_id, main_session_id, record_event
from .states import (
    EVENT_WAITING,
    OUTCOME_BLOCKED,
    OUTCOME_STOPPED,
    STATUS_COMPLETED,
    STATUS_STOPPED,
    STATUS_WAITING,
    WAITING_SUB_WORKFLOW,
)

MAX_SUB_WORKFLOW_DEPTH = 3


async def _chain(db: AsyncSession, run: WorkflowRun) -> list[WorkflowRun]:
    """The run and its ancestors (bounded: a longer chain is refused before it can exist)."""
    chain = [run]
    while chain[-1].parent_run_id and len(chain) <= MAX_SUB_WORKFLOW_DEPTH:
        parent = await db.get(WorkflowRun, chain[-1].parent_run_id)
        if parent is None:
            break
        chain.append(parent)
    return chain


async def start_sub_workflow(db: AsyncSession, run: WorkflowRun, node: PhasedNode, *, actor_id: str | None) -> None:
    from .records import WorkflowRunError, start_run
    from .run_end import fail_run

    if isinstance(node.config.get("handoff"), dict):
        from .handoff.service import offer_handoff

        flow, version = await _authored_child(db, run, node)
        await offer_handoff(db, run, node_id=node.id, contract=node.config["handoff"],
                            child_descriptor={"workflow_key": flow.key, "version_id": version.id})
        return
    key = str(node.config.get("workflow_key"))
    chain = await _chain(db, run)
    if any(item.workflow_key == key for item in chain):
        await fail_run(db, run, f"Sub-workflow '{key}' would start itself again (A → … → A).")
        return
    if len(chain) >= MAX_SUB_WORKFLOW_DEPTH:
        await fail_run(db, run, f"Sub-workflow '{key}' exceeds the nesting limit of {MAX_SUB_WORKFLOW_DEPTH}.")
        return
    run.status, run.waiting_kind = STATUS_WAITING, WAITING_SUB_WORKFLOW
    record_event(db, run, EVENT_WAITING, node_id=node.id, detail={"waiting_kind": WAITING_SUB_WORKFLOW})
    entry = dict(run.node_state or {}).get("entry")
    from .runtime_target.target import stored_target

    user = await db.get(User, run.requested_by)
    session_id = await main_session_id(db, run)
    session = await db.get(Session, session_id) if session_id else None
    try:
        child = await start_run(
            db, user=user, workflow_key=key, project_id=run.project_id,
            work_item_id=run.work_item_id, repository=run.repository, branch=run.branch, session=session,
            parent=run, parent_node_id=node.id, ticket_key=run.ticket_key,
            context={**{key: value for key, value in dict(run.context or {}).items() if key == "jira_project_key"},
                     **_handoff(run, node)},
            runtime_target=stored_target(run),  # the child runs where its parent runs
        )
    except WorkflowRunError as error:
        await fail_run(db, run, f"Sub-workflow '{key}' could not start: {error}")
        return
    state = dict(run.node_state or {})
    if (run.status == STATUS_WAITING and run.waiting_kind == WAITING_SUB_WORKFLOW
            and run.current_node_id == node.id and state.get("entry") == entry):
        # Only while the parent still waits here: a child that ended at once has already moved the parent on.
        run.node_state = {**state, "child_run_id": child.id}


async def _authored_child(db: AsyncSession, run: WorkflowRun, node: PhasedNode):
    """The typed child: the current published version, or exactly the authored pinned version and checksum."""
    from ...models import FlowDefinition, FlowDefinitionVersion
    from .engine import published_phased_flow
    from .handoff.contract import canonical_hash
    from .records import WorkflowRunError

    key = str(node.config.get("workflow_key"))
    pinned = node.config.get("child_version_id")
    if pinned is None:
        found = await published_phased_flow(db, key, run.project_id)
        if found is None:
            raise WorkflowRunError("needs_configuration", "The authored child is not published in this scope.")
        return found
    version = await db.get(FlowDefinitionVersion, str(pinned), populate_existing=True)
    flow = await db.get(FlowDefinition, version.flow_id, populate_existing=True) if version is not None else None
    if (version is None or flow is None or flow.key != key or version.status != "published"
            or canonical_hash(version.definition_json) != node.config.get("child_checksum")):
        # Never the newest version instead: a changed or unpublished pin is a configuration hold, not an upgrade.
        raise WorkflowRunError("needs_configuration", "The authored pinned child version changed or is unavailable.")
    return flow, version


def _handoff(run: WorkflowRun, node: PhasedNode) -> dict:
    """The recorded outputs the node hands to the child (``handoff``): its phases read them as inputs."""
    from .phase_outputs import HANDOFF_KEY, recorded_output

    kinds = [str(item) for item in node.config.get("handoff") or []] if isinstance(node.config.get("handoff"),
                                                                                  list) else []
    records = {kind: dict(envelope.get("record") or {}) for kind in kinds
               if (envelope := recorded_output(run, kind)) is not None}
    return {HANDOFF_KEY: records} if records else {}


def _child_outcome(child: WorkflowRun) -> str:
    if child.status == STATUS_COMPLETED and child.outcome:
        return child.outcome
    return OUTCOME_STOPPED if child.status == STATUS_STOPPED else OUTCOME_BLOCKED


async def child_finished(db: AsyncSession, child: WorkflowRun, *, actor_id: str | None) -> None:
    from .engine import resolve_current_node
    from .handoff.lifecycle import child_offer

    if await child_offer(db, child) is not None:
        return  # Typed completion resumes the original parent only in the later handoff sweep transaction.
    parent = await lock_run_id(db, child.parent_run_id)
    if (parent is None or parent.status != STATUS_WAITING or parent.waiting_kind != WAITING_SUB_WORKFLOW
            or parent.current_node_id != child.parent_node_id):
        return
    session_id = await main_session_id(db, child)
    session = await db.get(Session, session_id) if session_id else None
    if session is not None:
        await bind_session(db, parent, session, actor_id=actor_id)
    await resolve_current_node(db, parent, _child_outcome(child), actor_id=actor_id)


__all__ = ["child_finished", "start_sub_workflow"]
