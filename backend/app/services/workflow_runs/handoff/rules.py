"""The handoff's binding rules: its authored payload hash, the exact parent wait, the pinned child descriptor, the
offered sources and the receiver's proved rights."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import FlowDefinition, FlowDefinitionVersion, User, WorkflowRun
from ....models.runtime.workflow_handoff import WorkflowHandoff
from ....time_utils import utc_now
from ..records import WorkflowRunError
from ..runtime_target.target import parse_target
from .authority import confirmed_envelopes
from .contract import canonical_hash, refuse

RightsEvaluator = Callable[..., Awaitable[dict]]
WAITING_HANDOFF = "handoff"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def binding_payload(row: WorkflowHandoff) -> dict:
    return {"schema_version": row.schema_version, "parent_run_id": row.parent_run_id,
        "parent_node_id": row.parent_node_id, "parent_entry": row.parent_entry,
        "parent_state_version": row.parent_state_version, "parent_version_id": row.parent_version_id,
        "child_descriptor": row.child_descriptor, "requested_by": row.requested_by,
        "contract": row.contract, "envelopes": row.envelopes, "target_kind": row.target_kind,
        "target_key": row.target_key, "round": row.round, "deputy_active": row.deputy_active,
        "owner_history": row.owner_history,
        "expires_at": _utc(row.expires_at).isoformat()}


def _hash_valid(row: WorkflowHandoff) -> None:
    if canonical_hash(binding_payload(row)) != row.payload_hash:
        refuse("handoff_changed", "The authored offer bindings changed")


def _parent_valid(parent: WorkflowRun, row: WorkflowHandoff) -> None:
    if (parent.project_id != row.workspace_id or parent.flow_definition_version_id != row.parent_version_id
            or parent.requested_by != row.requested_by):
        refuse("handoff_changed", "The parent scope or version changed")
    if not row.detach or parent.status not in {"stopped", "completed"}:
        if (parent.status != "waiting" or parent.waiting_kind != WAITING_HANDOFF
                or parent.current_node_id != row.parent_node_id
                or dict(parent.node_state or {}).get("entry") != row.parent_entry
                or parent.state_version != row.parent_state_version):
            refuse("stale_parent", "The parent no longer waits on this exact offer")


async def _descriptor(db: AsyncSession, descriptor: dict, parent: WorkflowRun) -> dict:
    if (not isinstance(descriptor, dict) or set(descriptor) not in (
            {"workflow_key", "version_id"}, {"workflow_key", "version_id", "checksum"})):
        refuse("needs_configuration", "A pinned published child descriptor is required")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 180 for value in descriptor.values()):
        refuse("needs_configuration", "The child descriptor references are invalid")
    version = await db.get(FlowDefinitionVersion, descriptor["version_id"], populate_existing=True)
    flow = await db.get(FlowDefinition, version.flow_id, populate_existing=True) if version else None
    if (not version or version.status != "published" or not flow or not flow.is_active or flow.status != "published"
            or flow.key != descriptor["workflow_key"]
            or flow.project_id not in {None, parent.project_id}):
        refuse("needs_configuration", "The child version is not published in this scope")
    chain, cursor = set(), parent
    for _ in range(3):
        chain.add(cursor.workflow_key)
        if not cursor.parent_run_id:
            break
        cursor = await db.get(WorkflowRun, cursor.parent_run_id)
        if cursor is None:
            refuse("needs_configuration", "The parent chain cannot be proved")
    else:
        refuse("invalid_handoff", "The child would exceed the sub-workflow depth limit")
    if len(chain) >= 3:
        refuse("invalid_handoff", "The child would exceed the sub-workflow depth limit")
    if descriptor["workflow_key"] in chain:
        refuse("invalid_handoff", "A handoff cannot recursively start its parent workflow")
    checksum = canonical_hash(version.definition_json)
    if "checksum" in descriptor and descriptor["checksum"] != checksum:
        refuse("child_version_changed", "The pinned child definition content changed")
    return {"workflow_key": flow.key, "version_id": version.id, "checksum": checksum}


async def _sources_current(db: AsyncSession, parent: WorkflowRun, row: WorkflowHandoff) -> None:
    from .specification import require_spec_parent

    require_spec_parent(row)
    if await confirmed_envelopes(db, parent, row.contract["artefacts"]) != row.envelopes:
        refuse("source_changed", "The current confirmed artefact differs from the offered version")
    scope = row.contract["scope"]
    if parent.work_item_id != scope["work_item_id"] or parent.repository != scope["repository"]:
        refuse("handoff_changed", "The current parent data scope differs from the offer")
    await _descriptor(db, row.child_descriptor, parent)


async def _rights(db: AsyncSession, row: WorkflowHandoff, actor: User, runtime: dict | None,
                  evaluator: RightsEvaluator | None) -> dict:
    if evaluator is None:
        refuse("needs_configuration", "A receiver scope/runtime permission evaluator is required")
    proof = await evaluator(db=db, actor=actor, scope=row.contract["scope"], envelopes=row.envelopes,
                            runtime_target=runtime)
    digest = canonical_hash({"scope": row.contract["scope"], "envelopes": row.envelopes})
    if (not isinstance(proof, dict) or proof.get("allowed") is not True
            or proof.get("actor_id") != actor.id or proof.get("scope_digest") != digest):
        refuse("needs_configuration", "Current receiver source/scope rights could not be proved")
    if runtime is not None:
        try:
            requested, effective = parse_target(runtime), parse_target(proof.get("runtime_target"))
        except WorkflowRunError:
            refuse("needs_configuration", "The selected receiver runtime was not admitted")
        # The server's agents are its runners: a server or pool request is admitted as the runner it resolved to.
        pooled = isinstance(proof.get("runtime_target"), dict) and bool(proof["runtime_target"].get("pool"))
        if requested and effective and pooled and (requested["kind"] == "server" or requested.get("pool")):
            requested = effective
        if not requested or not effective or requested["kind"] != effective["kind"]:
            refuse("needs_configuration", "The selected receiver runtime was not admitted")
        if requested["kind"] == "device":
            pinned = ("device_id", "folder", "model")
            if (any(requested[key] != effective[key] for key in pinned)
                    or (requested["profile"] and requested["profile"] != effective["profile"])):
                refuse("needs_configuration", "The admitted runtime changed the selected device target")
        proof = {**proof, "runtime_target": effective}
    return proof


def _action_current(row: WorkflowHandoff, action: dict) -> None:
    _hash_valid(row)
    if (row.state != "offered" or row.payload_hash != action["payload_hash"] or row.round != action["round"]
            or row.state_version != action["expected_state_version"]):
        refuse("stale_handoff", "Read the current offer before responding")
    if _utc(utc_now()) >= _utc(row.expires_at):
        refuse("handoff_expired", "This offer has expired")


async def _cas(db: AsyncSession, row: WorkflowHandoff, **values) -> None:
    result = await db.execute(update(WorkflowHandoff).where(WorkflowHandoff.id == row.id,
        WorkflowHandoff.state_version == row.state_version).values(**values, state_version=row.state_version + 1,
        updated_at=utc_now()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        refuse("stale_handoff", "Another recipient or lifecycle action claimed this offer")
    await db.refresh(row)
