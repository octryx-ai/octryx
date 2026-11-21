"""An octryx-claude session started for a Work item follows that item's run from the first prompt.

- **At launch** (``POST sessions/register`` with ``X-Octryx-Work-Item``): the session attaches to the item's
  active run under the same rule as ``workflow_select`` (``attach.attach``: the run's Workspace, requester, Work item
  owner or admin). The answer carries the run contract, so the terminal shows the run banner before Claude Code
  starts. A refusal (unknown item, no right to act, ``run_followed_elsewhere`` while another octryx session works on
  the run — only an explicit ``workflow_select(run_id)`` takes it over) never refuses the launch: the session simply
  follows no run.
- **At the first prompt** (``POST sessions/prompt``) of a session whose item has no active run: the server proposes a
  workflow from the Work item and the prompt with the chat's proposal classifier (``workflow_routing.proposal``).
  A proposed (phased) workflow is a proposal the user confirms through ``workflow_select`` → ``workflow_confirm``
  (Claude Code's permission prompt). A phased run never starts by itself. The proposal is asked once per session.
- **At every later prompt** a bound session gets its current contract, so a decision taken in the platform since the
  last hook reaches the terminal before the model answers.

- **A device job's session** (``X-Octryx-Workflow-Run`` at registration): it follows the run its job carries
  from registration, under the same attach rule (:func:`device_run_answer`); the answer carries the contract, and a
  refusal refuses the registration with the attach reason (the device rejects the turn), so the agent never has to
  call ``workflow_select`` itself.

A session without a Work item and without a run is untouched: every function answers ``{}`` for it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ....models import Session, User
from ...content_security.untrusted_fence import untrusted_section
from ..records import WorkflowRunError, active_run_for_session
from .attach import active_run_of_item, attach, work_item_in_workspace
from .contract import run_contract, session_principal

PROPOSAL_METADATA = "run_proposal"
MAX_PROMPT_CHARS = 4000
MAX_ITEM_TEXT_CHARS = 2000
STATE_PROPOSED = "proposed"
STATE_NONE = "none"


async def launch_answer(db: AsyncSession, *, session: Session, user: User, workspace_id: str,
                        work_item_key: str) -> dict[str, Any]:
    """What the registration answer adds for a session started with a Work item."""
    if not work_item_key:
        return {}
    item = await work_item_in_workspace(db, work_item_key, workspace_id)
    if item is None:
        return {"workflow_run_attach": {"state": "needs_clarification", "reason": "work_item_unknown"}}
    run = await active_run_of_item(db, item)
    if run is None:
        return {"workflow_run_attach": {"state": "no_active_run", "proposal": "on_first_prompt"}}
    from ..access import run_access

    if await run_access(db, run, user) == "write" and await _followed_elsewhere(db, run, session):
        # Never a silent takeover: an explicit workflow_select(run_id) takes the run over, not a launch.
        return {"workflow_run_attach": {"state": "denied", "reason": "run_followed_elsewhere",
                                        "message": "Another octryx session follows this run; take it over with "
                                                   "workflow_select(run_id) if you mean to."}}
    try:
        run = await attach(db, gateway_session=session, user=user, workspace_id=workspace_id, run=run)
    except WorkflowRunError as error:
        return {"workflow_run_attach": {"state": "denied", "reason": error.code, "message": str(error)}}
    return {"workflow_run_attach": {"state": "attached"},
            "workflow_run": await run_contract(db, run, principal=user, session=session)}


async def device_run_answer(db: AsyncSession, *, session: Session, user: User, workspace_id: str,
                            run_id: str, job_id: str = "") -> dict[str, Any]:
    """The registration answer of a device job's session: bound to the run its job carries, or why not."""
    from ....models import WorkflowRun

    run = await active_run_for_session(db, session.id)
    if run is None or run.id != run_id:
        try:
            run = await attach(db, gateway_session=session, user=user, workspace_id=workspace_id,
                               run=await db.get(WorkflowRun, run_id), job_id=job_id)
        except WorkflowRunError as error:
            return {"workflow_run_attach": {"state": "denied", "reason": error.code, "message": str(error)}}
    return {"workflow_run_attach": {"state": "attached"},
            "workflow_run": await run_contract(db, run, principal=user, session=session)}


async def _followed_elsewhere(db: AsyncSession, run: Any, session: Session) -> bool:
    """Whether another session is the run's active octryx session (a terminal or a device job working on it)."""
    from sqlalchemy import select

    from ....models import WorkflowRunSession
    from .attach import ROLE_OCTRYX

    other = (await db.execute(select(WorkflowRunSession.id).where(
        WorkflowRunSession.run_id == run.id, WorkflowRunSession.role == ROLE_OCTRYX,
        WorkflowRunSession.active.is_(True), WorkflowRunSession.session_id != session.id,
    ).limit(1))).scalar_one_or_none()
    return other is not None


def _item_text(item: Any, prompt: str) -> str:
    description = str(getattr(item, "description", "") or "")[:MAX_ITEM_TEXT_CHARS]
    # The item is written in its source (Jira, ServiceNow): an untrusted block before the user's own prompt.
    item_block = untrusted_section("work item", f"{item.source_key}: {item.title or ''}\n{description}",
                                   source="the work item source")
    return f"{item_block}\n\n{prompt[:MAX_PROMPT_CHARS]}".strip()


async def _propose(db: AsyncSession, *, session: Session, workspace_id: str, item: Any,
                   prompt: str) -> dict[str, Any]:
    from ...workflow_routing.proposal import resolve_workflow_proposal_for_turn, workflow_proposal_of
    from ..engine import published_phased_flow

    resolution = await resolve_workflow_proposal_for_turn(db, user_message=_item_text(item, prompt),
                                                          project_id=workspace_id)
    record = workflow_proposal_of(resolution) or {}
    key = str(record.get("workflow_key") or "")
    proposal = {"workflow_key": key or None, "workflow_title": record.get("workflow_title"),
                "confidence": record.get("confidence"), "reason": record.get("reason"),
                "reason_code": record.get("reason_code"), "change_capable": record.get("change_capable")}
    if not key or record.get("status") != "needs_confirmation":
        return {"state": STATE_NONE, **proposal}
    proposal["phased"] = await published_phased_flow(db, key, workspace_id) is not None
    # The user confirms through workflow_select → workflow_confirm (never by itself).
    return {"state": STATE_PROPOSED, **proposal,
            "next": {"tool": "workflow_select", "arguments": {"workflow_key": key, "work_item": item.source_key}}}


async def prompt_answer(db: AsyncSession, *, session: Session, workspace_id: str, work_item_key: str,
                        prompt: str) -> dict[str, Any]:
    """The prompt hook's answer: the bound run's contract, or once the first prompt's workflow proposal."""
    run = await active_run_for_session(db, session.id)
    if run is not None:
        return {"workflow_run": await run_contract(db, run, principal=await session_principal(db, session))}
    from ...work_item_analysis.seat_session import pinned_item_id

    metadata = dict(session.metadata_ or {})
    if not work_item_key or pinned_item_id(session) is not None or PROPOSAL_METADATA in metadata:
        return {}  # an ``analyze`` session keeps its fixed analysis tool set: never a proposal
    item = await work_item_in_workspace(db, work_item_key, workspace_id)
    if item is None or not str(prompt or "").strip():
        return {}
    proposal = await _propose(db, session=session, workspace_id=workspace_id, item=item, prompt=str(prompt))
    session.metadata_ = {**dict(session.metadata_ or {}), PROPOSAL_METADATA: proposal}
    flag_modified(session, "metadata_")
    await db.flush()
    return {"workflow_proposal": proposal}


__all__ = ["PROPOSAL_METADATA", "device_run_answer", "launch_answer", "prompt_answer"]
