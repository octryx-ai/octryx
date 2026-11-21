"""Allocate a receiver-owned child only as DB rows inside atomic acceptance."""
from __future__ import annotations

import copy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowDefinition, FlowDefinitionVersion, Session, User, WorkflowRun, WorkflowRunSession
from ...secure_work.access import get_scoped_work_item
from ..graph_validation import validate_phased_definition
from ..phase_agents import phase_agent_db_errors
from ..phase_outputs import HANDOFF_KEY
from ..records import RUN_METADATA_KEY
from ..runtime_target.target import apply_to_thread, parse_target, with_target
from .contract import canonical_hash, refuse
from .permissions import rights_evaluator

HANDOFF_BINDING_KEY = "handoff_binding"
PENDING_COMMIT = "handoff_commit_pending"


async def allocate_child(*, db: AsyncSession, parent: WorkflowRun, handoff, actor: User, runtime_proof: dict) -> dict:
    """No start_run, advance, clone, credential resolution or provider I/O occurs in this factory."""
    descriptor = handoff.child_descriptor
    if not isinstance(descriptor, dict) or set(descriptor) != {"workflow_key", "version_id", "checksum"}:
        refuse("needs_configuration", "A server-pinned child version and checksum are required")
    version = (await db.execute(select(FlowDefinitionVersion).where(
        FlowDefinitionVersion.id == descriptor["version_id"]).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.id == version.flow_id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none() if version else None
    if (version is None or version.status != "published" or flow is None or flow.status != "published"
            or not flow.is_active or flow.key != descriptor["workflow_key"]
            or flow.project_id not in (None, handoff.workspace_id)
            or canonical_hash(version.definition_json) != descriptor["checksum"]):
        refuse("needs_configuration", "The pinned published child definition changed or is unavailable")
    definition = dict(version.definition_json or {})
    if not validate_phased_definition(definition)["valid"]:
        refuse("needs_configuration", "The pinned published child graph is not valid")
    agent_errors = await phase_agent_db_errors(db, definition)
    if agent_errors:
        refuse("needs_configuration", agent_errors[0]["message"])
    scope = handoff.contract["scope"]
    current = await rights_evaluator(db=db, actor=actor, scope=scope, envelopes=handoff.envelopes,
                                    runtime_target=runtime_proof.get("runtime_target"))
    if (runtime_proof.get("allowed") is not True or current["actor_id"] != runtime_proof.get("actor_id")
            or current["scope_digest"] != runtime_proof.get("scope_digest")
            or current["runtime_target"] is None
            or parse_target(current["runtime_target"]) != parse_target(runtime_proof.get("runtime_target"))
            or handoff.child_run_id or handoff.receiver_session_id):
        refuse("needs_configuration", "Allocation needs an unchanged current receiver proof and an empty child slot")
    from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_NOT_ALLOWED

    from ..runtime_target.server_build import logger as server_build_log
    from ..runtime_target.server_build import server_build_refusal

    # A child that builds or tests never runs on the server: the receiver chooses a device.
    if (server_build := server_build_refusal(current["runtime_target"], definition=definition)) is not None:
        server_build_log.warning("server_build_not_allowed: where=handoff_child workflow=%s steps=%s actor=%s",
                                 flow.key, server_build[1], actor.id)
        refuse(SERVER_BUILD_NOT_ALLOWED, server_build[0])
    item = await get_scoped_work_item(db, actor, scope["work_item_id"]) if scope["work_item_id"] else None
    binding = {"handoff_id": handoff.id, "parent_run_id": parent.id, "parent_node_id": handoff.parent_node_id,
        "parent_entry": handoff.parent_entry, "actor_id": actor.id, "owner_epoch": handoff.owner_epoch + 1,
        "payload_hash": handoff.payload_hash, "scope_digest": current["scope_digest"],
        "child_version_id": version.id, "child_checksum": descriptor["checksum"]}
    records = {kind: copy.deepcopy(proof["envelope"]["record"]) for kind, proof in handoff.envelopes.items()}
    context = with_target({HANDOFF_KEY: records, "handoff_approved_envelopes": copy.deepcopy(handoff.envelopes),
                           HANDOFF_BINDING_KEY: binding}, current["runtime_target"], actor_id=actor.id)
    child = WorkflowRun(project_id=handoff.workspace_id, workflow_kind="phased", workflow_key=flow.key,
        title=flow.name, workflow_version=f"v{version.version}", flow_definition_version_id=version.id,
        requested_by=actor.id, responsible_user_id=actor.id, responsible_source="requester",
        parent_run_id=parent.id, parent_node_id=handoff.parent_node_id,
        work_item_id=scope["work_item_id"], ticket_key=item.source_key if item and item.source_type == "jira" else None,
        repository=scope["repository"], context=context, status="waiting", waiting_kind=PENDING_COMMIT,
        current_node_id=None, node_state={"entry": 0}, state_version=0)
    session = Session(user_id=actor.id, project_id=handoff.workspace_id, parent_session_id=None,
                      origin="chat", status="active", metadata_={HANDOFF_BINDING_KEY: copy.deepcopy(binding)})
    apply_to_thread(session, current["runtime_target"])
    db.add_all([child, session])
    await db.flush()
    session.metadata_ = {**session.metadata_, RUN_METADATA_KEY: child.id}
    db.add(WorkflowRunSession(run_id=child.id, session_id=session.id, role="main", active=True,
        runtime="octryx_claude" if current["runtime_target"]["kind"] == "terminal" else "chat"))
    await db.flush()
    return {"child_run_id": child.id, "receiver_session_id": session.id}


__all__ = ["allocate_child", "HANDOFF_BINDING_KEY", "PENDING_COMMIT"]
