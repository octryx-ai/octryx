"""The spec-origin decider and actual-viewer authority of a spec-bound engineering child.

``decider: spec_origin`` routes an interactive decision to the exact human who confirmed the accepted spec: the
``decided_by`` of the latest current human spec confirmation held in the child's accepted durable handoff. It is
derived only after the accepted owner's lifecycle and source authority are proved again, and only while that person
is still an active human member of the Workspace. It never reads the child requester, a role label, model arguments
or the idea confirmation, and it grants nothing else: owner, execution, Session and runtime stay with the engineer.

A spec-bound run's source-backed projections are a read by their actual viewer: the viewer's own current source
authority over the accepted spec is resolved independently (``resolve_viewer_spec``); the owner's proof is no grant.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun, WorkflowRunDecision
from ..records import WorkflowRunError

UNRESOLVED = "spec_origin_unresolved"
INACTIVE = "spec_origin_inactive"


async def spec_bound(db: AsyncSession, run: WorkflowRun) -> bool:
    """The run consumes an accepted spec: its pinned graph declares it, or a typed spec handoff binds it."""
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
    """``((user_id,), "")`` for the current spec-origin human, else ``((), reason)``; never a requester fallback."""
    from ..handoff.specification import has_spec_handoff, resolve_accepted_spec
    from ..work_roles import active_human

    if not await has_spec_handoff(db, run):
        return (), UNRESOLVED
    owner = await active_human(db, str(run.requested_by or ""))
    if owner is None:
        return (), UNRESOLVED
    try:
        # The accepted owner's lifecycle, the exact durable proof and its source authority, as the owner.
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
    """The accepted spec snapshot as ``viewer`` may read it now, else ``SpecificationUnavailable``."""
    from ..handoff.specification import resolve_viewer_spec
    from .lineage import SpecificationUnavailable

    if not isinstance(viewer, User):
        raise SpecificationUnavailable("principal_unavailable")
    try:
        return await resolve_viewer_spec(db, run, viewer=viewer)
    except WorkflowRunError as error:
        raise SpecificationUnavailable("accepted_spec_unavailable") from error


async def require_decider_spec_authority(db: AsyncSession, run: WorkflowRun, user: User) -> None:
    """Final decision recheck: a spec-bound decision needs its decider's own current source authority."""
    from .lineage import SpecificationUnavailable

    if not await spec_bound(db, run):
        return
    try:
        await viewer_spec(db, run, user)
    except SpecificationUnavailable as error:
        raise WorkflowRunError("needs_configuration", "Your current access to the accepted specification's sources "
                                                      "could not be verified; nothing was decided.", 409) from error


__all__ = ["INACTIVE", "UNRESOLVED", "require_decider_spec_authority", "spec_bound", "spec_origin", "viewer_spec"]
