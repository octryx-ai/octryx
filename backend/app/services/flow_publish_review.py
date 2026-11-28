"""Four-eyes publish for every workflow that runs in phases (the same rule as for fragments). A phased version is
published by an admin other than its author."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FlowDefinition, FlowDefinitionVersion, User
from ..time_utils import utc_now

REVIEW_KEY = "review"
REVIEW_AWAITING = "awaiting_approval"
REVIEW_APPROVED = "approved"
WORKFLOW_FOUR_EYES_REASON = "workflow_four_eyes"
REVIEW_NOT_NEEDED = "review_not_needed"
NOT_THE_AUTHOR = "review_by_author_only"
NOT_A_DRAFT = "review_not_a_draft"


def _definition(version: FlowDefinitionVersion) -> dict[str, Any]:
    return dict(version.definition_json or {})


def is_shipped_seed(version: FlowDefinitionVersion) -> bool:
    from .workflow_runs.canvas_layout import LAYOUT_KEY
    from .workflow_runs.fragments.store import is_fragment, is_seeded_fragment
    from .workflow_runs.seeding import SEED_MARKER, definition_digest

    definition = _definition(version)
    if is_fragment(definition):
        return is_seeded_fragment(version)  # the API strips the fragment marker on create and on every draft
    settings = dict(version.runtime_settings or {})
    if settings.get("seed") != SEED_MARKER or not settings.get("seed_digest"):
        return False
    shipped = str(settings["seed_digest"])
    return shipped in {definition_digest(definition),
                       definition_digest({key: value for key, value in definition.items() if key != LAYOUT_KEY})}


def needs_four_eyes(version: FlowDefinitionVersion) -> bool:
    from .workflow_runs.fragments.store import is_fragment
    from .workflow_runs.graph import is_phased_definition

    definition = _definition(version)
    return (is_fragment(definition) or is_phased_definition(definition)) and not is_shipped_seed(version)


def _refusal(version: FlowDefinitionVersion) -> HTTPException:
    from .workflow_runs.fragments.store import FOUR_EYES_REASON, is_fragment

    if is_fragment(_definition(version)):
        return HTTPException(status_code=409, detail={
            "reason": FOUR_EYES_REASON,
            "message": "A fragment version is published by an admin other than its author.",
        })
    return HTTPException(status_code=409, detail={
        "reason": WORKFLOW_FOUR_EYES_REASON,
        "message": "A workflow version is published by an admin other than its author: request a review, then a "
                   "second admin publishes it.",
    })


async def require_publish_four_eyes(
    db: AsyncSession, version: FlowDefinitionVersion, current_user: User, *, shipped: bool = False
) -> dict[str, Any]:
    # The approval keys are written after caller metadata, so a request body never sets its own approval.
    if shipped or not needs_four_eyes(version):
        return {}
    from .governance.four_eyes import decide_four_eyes, record_self_approval_audit

    decision = await decide_four_eyes(db, version.created_by, current_user.id, authors=[version.created_by])
    if not decision.approved:
        raise _refusal(version)
    project_id = await db.scalar(select(FlowDefinition.project_id).where(FlowDefinition.id == version.flow_id))
    record_self_approval_audit(db, decision, resource_type="flow_definition_version", resource_id=version.id,
                               approval_id=version.id, project_id=project_id)
    review = dict(dict(version.publish_metadata or {}).get(REVIEW_KEY) or {})
    review.update(state=REVIEW_APPROVED, approved_by=current_user.id, approved_at=utc_now().isoformat(),
                  approval_mode=decision.approval_mode)
    return {"approval_mode": decision.approval_mode, "four_eyes_status": decision.status, REVIEW_KEY: review}


async def publish_permission(db: AsyncSession, version: FlowDefinitionVersion, user_id: str) -> dict[str, Any]:
    if not needs_four_eyes(version):
        return {"can_publish": True, "publish_reason": ""}
    from .governance.four_eyes import decide_four_eyes

    decision = await decide_four_eyes(db, version.created_by, user_id, authors=[version.created_by])
    if decision.approved:
        return {"can_publish": True, "publish_reason": ""}
    return {"can_publish": False,
            "publish_reason": "A second admin publishes this: four-eyes is on for this platform. Request publishing."}


async def request_review(db: AsyncSession, *, version_id: str, current_user: User) -> dict[str, Any]:
    from .flow_definitions import get_flow_definition, validate_flow_definition
    from .flow_version_state import FlowVersionStateError, load_flow_version, load_version_flow

    try:
        version = await load_flow_version(db, version_id)
        flow = await load_version_flow(db, version)
    except FlowVersionStateError as error:
        raise error.to_http() from None
    if flow.status == "archived" or not flow.is_active or version.status != "draft":
        raise HTTPException(status_code=409, detail={
            "reason": NOT_A_DRAFT, "message": "Only a draft of an active workflow can be reviewed."})
    if not needs_four_eyes(version):
        raise HTTPException(status_code=409, detail={
            "reason": REVIEW_NOT_NEEDED, "message": "This version is published without a second admin."})
    if version.created_by != current_user.id:
        raise HTTPException(status_code=403, detail={
            "reason": NOT_THE_AUTHOR, "message": "The author of the version requests its review."})
    report = validate_flow_definition(_definition(version))
    if not report["valid"]:
        version.validation_report = report
        await db.flush()
        raise HTTPException(status_code=422, detail=report)
    metadata = dict(version.publish_metadata or {})
    if dict(metadata.get(REVIEW_KEY) or {}).get("state") != REVIEW_AWAITING:
        metadata[REVIEW_KEY] = {"state": REVIEW_AWAITING, "requested_by": current_user.id,
                                "requested_at": utc_now().isoformat()}
        version.publish_metadata = metadata
        from ..models import AuditLog

        db.add(AuditLog(user_id=current_user.id, action="flow_version_review_requested",
                        resource_type="flow_definition_version", resource_id=version.id,
                        project_id=flow.project_id,
                        details={"flow_id": flow.id, "version": version.version}))
        await db.flush()
    return await get_flow_definition(db, flow_id=flow.id)


__all__ = [
    "REVIEW_APPROVED",
    "REVIEW_AWAITING",
    "REVIEW_KEY",
    "WORKFLOW_FOUR_EYES_REASON",
    "is_shipped_seed",
    "publish_permission",
    "needs_four_eyes",
    "request_review",
    "require_publish_four_eyes",
]
