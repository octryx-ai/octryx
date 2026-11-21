"""A confirmation the platform prepares but never gives: ``config.auto_accept: "product_owner"``.

Wait for the product owner in the Studio by default; ``auto_accept=review_passed`` only as an
explicit opt-in (benchmarks/unattended runs). While waiting, the product owner is notified and the run is visible as
"waiting for spec approval".

The node revises like ``review_passed`` (the review's findings and the Spec Studio's open points go back to the agent
within ``auto_revise``), but where ``review_passed`` would confirm, the run waits for the product owner:

- ``waiting.reason`` is ``spec_approval`` when the run has a Spec Studio (``product_owner_approval`` otherwise), so the
  run card, the run lists and the Inbox say what it waits for;
- the person responsible for the run (else the person who started it) gets one notification with the Studio's
  address, once per wait;
- event ``waiting_for_product_owner`` with why the platform would have accepted (or why it stopped revising).

A benchmark or an unattended run opts into ``review_passed``: on the node (its workflow copy in the designer), or for
a whole Workspace with the setting ``spec_approval: "review_passed"`` (``PUT /api/v1/projects/{id}/config``, audited
like every Workspace setting). A Workspace copy of the workflow needs a second admin to publish (four-eyes); the
setting does not, and the workflow stays the shipped one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .records import record_event

RULE_PRODUCT_OWNER = "product_owner"
REASON_SPEC_APPROVAL = "spec_approval"
REASON_PRODUCT_OWNER = "product_owner_approval"
EVENT_WAITING_FOR_PRODUCT_OWNER = "waiting_for_product_owner"
NOTIFICATION_TYPE = "workflow_run_spec_approval"
SPEC_APPROVAL_CONFIG_KEY = "spec_approval"
SPEC_APPROVAL_VALUES = (RULE_PRODUCT_OWNER, "review_passed")
WORKSPACE_OPT_IN = "Workspace setting spec_approval: review_passed"


def normalize_spec_approval(value: Any) -> str:
    """The Workspace setting's value (the project-config owner hook); ``ValueError`` for anything else."""
    found = str(value or "").strip()
    if found not in SPEC_APPROVAL_VALUES:
        raise ValueError(f"spec_approval: one of {', '.join(SPEC_APPROVAL_VALUES)}")
    return found


async def workspace_accepts_review(db: AsyncSession, run: WorkflowRun) -> bool:
    """Whether the run's Workspace opted out of the product owner wait (benchmarks, unattended runs)."""
    if not run.project_id:
        return False
    from ...models import Project

    project = await db.get(Project, run.project_id)
    config = project.config if project is not None and isinstance(project.config, dict) else {}
    return config.get(SPEC_APPROVAL_CONFIG_KEY) == "review_passed"


def studio_address(run_id: str) -> str:
    """The Spec Studio of a run in the web client (``frontend/chat/src/chat/specStudio/specStudioAddress.ts``)."""
    return f"/chat?area=work&work_view=spec_studio&run_id={run_id}"


def _has_studio(run: WorkflowRun) -> bool:
    from .spec_studio.service import artefact_of

    return artefact_of(run) is not None


def _text(run: WorkflowRun, studio: bool, why: str) -> tuple[str, str]:
    if studio:
        title = f"Spec ready for your approval: {run.title}"
        body = ("The specification waits for your approval in the Spec Studio: decide the open questions, comment "
                "on the mock and approve, or send it back with your answers.")
    else:
        title = f"Your decision: {run.title}"
        body = "The run waits for your decision in its run card."
    return title, f"{body}\n\nPlatform check: {why}" if why else body


async def wait_for_product_owner(db: AsyncSession, run: WorkflowRun, node: Any, *, why: str = "") -> bool:
    """Mark the wait and tell the product owner, once per wait. Always ``False``: the run does not move."""
    state = dict(run.node_state or {})
    waiting = dict(state.get("waiting") or {})
    if waiting.get("product_owner_notified"):
        return False
    studio = _has_studio(run)
    reason = REASON_SPEC_APPROVAL if studio else REASON_PRODUCT_OWNER
    recipient = run.responsible_user_id or run.requested_by
    title, body = _text(run, studio, why)
    link = studio_address(run.id) if studio else f"/workflow-runs/{run.id}"
    waiting.update(reason=reason, question=body.split("\n\n")[0], product_owner_notified=utc_now().isoformat())
    if studio:
        waiting["title"] = "Waiting for spec approval"
    run.node_state = {**state, "waiting": waiting}
    if recipient:
        from ..team_notification.service import create_notification

        await create_notification(db, user_id=recipient, notification_type=NOTIFICATION_TYPE, title=title[:200],
                                  body=body, link=link, project_id=run.project_id)
    record_event(db, run, EVENT_WAITING_FOR_PRODUCT_OWNER, node_id=getattr(node, "id", run.current_node_id),
                 detail={"reason": reason, "why": why, "notified": bool(recipient), "link": link})
    return False


__all__ = ["EVENT_WAITING_FOR_PRODUCT_OWNER", "NOTIFICATION_TYPE", "REASON_PRODUCT_OWNER", "REASON_SPEC_APPROVAL",
           "RULE_PRODUCT_OWNER", "SPEC_APPROVAL_CONFIG_KEY", "WORKSPACE_OPT_IN", "normalize_spec_approval",
           "studio_address", "wait_for_product_owner", "workspace_accepts_review"]
