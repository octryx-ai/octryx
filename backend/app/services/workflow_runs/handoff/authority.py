"""Current human candidates and exact human-confirmed parent artefacts, without grants."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import IdentityGroup, ProjectGroup, UserGroup, WorkflowRun, WorkflowRunDecision
from ....models.runtime.workflow_handoff import WorkflowHandoff, WorkflowHandoffResponse
from ..phase_outputs import output_hash, recorded_output
from ..work_roles import lock_actor_membership, work_role_members, workspace_humans
from .contract import refuse


async def candidates(db: AsyncSession, row: WorkflowHandoff, *, include_declined: bool = False) -> tuple[str, ...]:
    members = await workspace_humans(db, row.workspace_id)
    if row.target_kind == "person":
        ids = {row.target_key} & set(members)
    elif row.target_kind == "role":
        ids = set(await work_role_members(db, row.workspace_id, row.target_key))
    elif row.target_kind == "group":
        ids = set((await db.execute(select(UserGroup.user_id).join(IdentityGroup,
            IdentityGroup.id == UserGroup.group_id).join(ProjectGroup, ProjectGroup.group_id == IdentityGroup.id)
            .where(IdentityGroup.id == row.target_key, IdentityGroup.is_active.is_(True),
                   ProjectGroup.project_id == row.workspace_id))).scalars()) & set(members)
    else:
        ids = set()
    if not include_declined:
        declined = set((await db.execute(select(WorkflowHandoffResponse.user_id).where(
            WorkflowHandoffResponse.handoff_id == row.id, WorkflowHandoffResponse.round == row.round))).scalars())
        ids -= declined
    return tuple(sorted(ids))


async def require_candidate(db: AsyncSession, row: WorkflowHandoff, actor_id: str, *, lock: bool = False) -> None:
    if lock:
        await lock_actor_membership(db, row.workspace_id, actor_id,
            role_key=row.target_key if row.target_kind == "role" else None)
    if actor_id not in await candidates(db, row):
        refuse("not_handoff_recipient", "Only a currently eligible human recipient can act", 403)


async def confirmed_envelopes(db: AsyncSession, parent: WorkflowRun, kinds: list[str]) -> dict:
    # A later changed or stopped decision invalidates the old confirmation even with unchanged output names.
    decisions = list((await db.execute(select(WorkflowRunDecision).where(
        WorkflowRunDecision.run_id == parent.id, WorkflowRunDecision.kind == "confirmation")
        .order_by(WorkflowRunDecision.created_at.desc(), WorkflowRunDecision.id.desc())
        .execution_options(populate_existing=True))).scalars())
    result = {}
    for kind in kinds:
        envelope = recorded_output(parent, kind)
        if not envelope or not isinstance(envelope.get("record"), dict) or type(envelope.get("version")) is not int:
            refuse("needs_configuration", "The parent has no provable artefact envelope")
        if envelope.get("hash") != output_hash(envelope["record"]):
            refuse("source_changed", "The parent artefact body differs from its recorded hash")
        relevant = [d for d in decisions if d.subject == kind or dict(d.payload or {}).get("shows") == kind]
        decision = relevant[0] if relevant else None
        shown = dict(dict(decision.payload or {}).get("output") or {}) if decision else {}
        if (decision is None or decision.action != "confirmed" or not decision.decided_by or not decision.payload_hash
                or decision.payload_hash != output_hash(decision.payload)
                or shown.get("version") != envelope["version"] or shown.get("hash") != envelope["hash"]):
            refuse("needs_configuration", "The exact current artefact has no human confirmation")
        body = {key: value for key, value in shown.items() if key not in {"version", "hash"}}
        if output_hash(body) != envelope["hash"]:
            refuse("source_changed", "The confirmed body differs from the current artefact")
        result[kind] = {"envelope": envelope, "decision_id": decision.id,
                        "decision_hash": decision.payload_hash, "decided_by": decision.decided_by}
    return result
