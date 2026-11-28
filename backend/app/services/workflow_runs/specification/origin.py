"""The spec-origin decider and actual-viewer authority of a spec-bound engineering child."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun, WorkflowRunDecision
from ..records import WorkflowRunError

UNRESOLVED = "spec_origin_unresolved"
INACTIVE = "spec_origin_inactive"


async def spec_bound(db: AsyncSession, run: WorkflowRun) -> bool:
    from ..data_flow import receives_spec
    from ..graph import graph_for_run
    from ..handoff.specification import has_spec_handoff

    if run.workflow_kind != "phased":
        return False
    if receives_spec(await graph_for_run(db, run)):
        return True
    try:
        return await has_spec_handoff(db, run)
    except WorkflowRunError:
        return True  # a typed receiver marker without its durable offer: protected, never a permissive view


async def spec_origin(db: AsyncSession, run: WorkflowRun, members: dict[str, User]) -> tuple[tuple[str, ...], str]:
    # Never a requester fallback.
    from ..handoff.specification import has_spec_handoff, resolve_accepted_spec
    from ..work_roles import active_human

    if not await has_spec_handoff(db, run):
        return (), UNRESOLVED
    owner = await active_human(db, str(run.requested_by or ""))
    if owner is None:
        return (), UNRESOLVED
    try:
        snapshot = await resolve_accepted_spec(db, run, principal=owner)
    except WorkflowRunError:
        return (), UNRESOLVED
    confirmation = dict(snapshot.get("confirmation") or {})
    origin = confirmation.get("decided_by")
    parent_id = dict(snapshot.get("binding") or {}).get("parent_run_id")
    decision = await db.get(WorkflowRunDecision, str(confirmation.get("decision_id") or ""), populate_existing=True)
    if (not isinstance(origin, str) or not origin or decision is None or decision.run_id != parent_id
            or decision.run_id != run.parent_run_id or decision.kind != "confirmation"
            or decision.action != "confirmed" or decision.decided_by != origin
            or decision.payload_hash != confirmation.get("decision_hash")
            or dict(decision.payload or {}).get("shows", decision.subject) != "spec"):
        return (), UNRESOLVED
    if origin not in members:
        return (), INACTIVE
    return (origin,), ""


async def viewer_spec(db: AsyncSession, run: WorkflowRun, viewer: Any) -> dict:
    from ..handoff.specification import resolve_viewer_spec
    from .lineage import SpecificationUnavailable

    if not isinstance(viewer, User):
        raise SpecificationUnavailable("principal_unavailable")
    try:
        return await resolve_viewer_spec(db, run, viewer=viewer)
    except WorkflowRunError as error:
        raise SpecificationUnavailable("accepted_spec_unavailable") from error


async def require_decider_spec_authority(db: AsyncSession, run: WorkflowRun, user: User) -> None:
    from .lineage import SpecificationUnavailable

    if not await spec_bound(db, run):
        return
    try:
        await viewer_spec(db, run, user)
    except SpecificationUnavailable as error:
        raise WorkflowRunError("needs_configuration", "Your current access to the accepted specification's sources "
                                                      "could not be verified; nothing was decided.", 409) from error


__all__ = ["INACTIVE", "UNRESOLVED", "require_decider_spec_authority", "spec_bound", "spec_origin", "viewer_spec"]
