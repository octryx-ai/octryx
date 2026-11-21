"""The responsible person of a workflow run ("Responsible person and approvals").

- **Who** (``WorkflowRun.responsible_user_id`` / ``responsible_source``): a run a person starts has its requester
  (``requester``); a sub-workflow inherits its parent's. An automatic start for a Work item (``start_run(...,
  automatic=True)``, the intake automation) walks ``RESPONSIBLE_CHAIN`` over the item's people:
  the **reporter** (Jira ``reporter``; ServiceNow ``caller_id``, stored as ``WorkItem.reporter`` by the intake),
  else the **assignee** (Jira ``assignee``; ServiceNow ``assigned_to``). A link counts only when it names exactly one
  active human member of the run's Workspace (username, email or a linked account's id/username, as the
  ``item_owner`` decider matches); an inactive, foreign or ambiguous person is skipped. Nobody: ``None``, the
  broadcast case — the existing decision audience applies unchanged (the "first to accept" is a later step).
- **What it gives**: the run's interactive decisions go to the responsible person **in addition** to today's
  rights, never instead and never to anyone else: the confirmations, replies and acceptances of a node without an
  authored decider and of a ``decider: requester`` node (``decider.resolve_decider``), and the tool approval of a
  run's platform step (``hitl_decisions``); the person's attention queue and phone push list them
  (``attention.run_items``). A four-eyes approval keeps the platform approval rule (admin, four-eyes), and a device
  approval stays the device owner's own consent (``devices.jobs``): those rights do not move. Nothing decides on
  its own: without an answer the run keeps waiting (and pauses on its own timeout, as today).
- **Take over** (run action ``take_over``): a person with write access to the run (``access.run_access``: the
  requester, the Work item owner, a platform admin) becomes responsible (``taken_over``). The previous responsible
  person keeps every other right (the requester stays the requester); an audit row and a run event record it. A
  platform admin outside the run's Workspace decides as the responsible person only after this explicit takeover;
  starting a run does not make them a decider. Such an admin who started the run (responsible as ``requester``)
  takes it over themselves (**self-take-over**, ``may_self_take_over``): the source becomes ``taken_over``, audited
  like any takeover. Anyone else who is already responsible is refused (``already_responsible``); a non-admin outside
  the Workspace never becomes a decider this way.
- ``accepted``: the receiver of an accepted handover (``run_handover``) becomes the requester and the responsible.

The chain is a module constant for now; it becomes a per-workflow setting later (spec: "per workflow and
configurable").
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from .records import WorkflowRunError, lock_run, record_event
from .states import ACTIVE_STATUSES

SOURCE_REQUESTER = "requester"
SOURCE_REPORTER = "reporter"
SOURCE_ASSIGNEE = "assignee"
SOURCE_TAKEN_OVER = "taken_over"
SOURCE_ACCEPTED = "accepted"
SOURCES = frozenset({SOURCE_REQUESTER, SOURCE_REPORTER, SOURCE_ASSIGNEE, SOURCE_TAKEN_OVER, SOURCE_ACCEPTED})
# The automatic start's chain, in order. Each link names the Work item column that carries it.
RESPONSIBLE_CHAIN: tuple[str, ...] = (SOURCE_REPORTER, SOURCE_ASSIGNEE)
_ITEM_FIELDS = {SOURCE_REPORTER: "reporter", SOURCE_ASSIGNEE: "assignee"}

ACTION_TAKE_OVER = "take_over"
TAKE_OVER_ACTION = {"key": ACTION_TAKE_OVER, "label": "Take over (become responsible)", "input": None}
SELF_TAKE_OVER_ACTION = {"key": ACTION_TAKE_OVER, "label": "Take over (decide this run yourself)", "input": None}
EVENT_TAKEN_OVER = "responsible_taken_over"
AUDIT_TAKEN_OVER = "workflow_run.taken_over"


async def _member_named(db: AsyncSession, identifier: str, members: dict[str, User]) -> str | None:
    """The one Workspace member ``identifier`` names (username, email, linked account id/username), else None."""
    from ..linked_accounts.resolution import account_names

    wanted = identifier.strip().lower()
    if not wanted or not members:
        return None
    linked = await account_names(db, set(members))
    matches = [user.id for user in members.values() if wanted in {
        str(user.username or "").lower(), str(user.email or "").lower(), *linked.get(user.id, set())} - {""}]
    return matches[0] if len(matches) == 1 else None


async def responsible_for(db: AsyncSession, work_item: WorkItem | None, project_id: str | None, *,
                          chain: tuple[str, ...] = RESPONSIBLE_CHAIN) -> tuple[str, str] | None:
    """``(user id, source)`` of the first chain link that is an active human member of the Workspace, else None."""
    from .work_roles import workspace_humans

    if work_item is None:
        return None
    members = await workspace_humans(db, project_id or work_item.project_id)
    for source in chain:
        field = _ITEM_FIELDS.get(source)
        user_id = await _member_named(db, str(getattr(work_item, field, None) or ""), members) if field else None
        if user_id:
            return user_id, source
    return None


async def initial_responsible(db: AsyncSession, *, user: User, item: WorkItem | None, project_id: str | None,
                              parent: WorkflowRun | None = None, automatic: bool = False
                              ) -> tuple[str | None, str | None]:
    """At run start: a sub-workflow inherits its parent's; an automatic start walks the chain (None when nobody
    resolves); a person's start keeps the requester."""
    if parent is not None and parent.responsible_user_id:
        return parent.responsible_user_id, parent.responsible_source
    if automatic:
        resolved = await responsible_for(db, item, project_id)
        return resolved if resolved is not None else (None, None)
    return user.id, SOURCE_REQUESTER


def is_responsible(run: WorkflowRun | None, user: User | None) -> bool:
    return bool(run is not None and user is not None and run.responsible_user_id
                and run.responsible_user_id == user.id)


async def responsible_decider(db: AsyncSession, run: WorkflowRun) -> tuple[str, ...]:
    """The responsible person as an extra decider: an active human who is a current member of the run's Workspace,
    or a platform admin who took the run over explicitly (``taken_over``); empty otherwise. A platform admin who only
    started the run (``requester``) is no default decider outside their Workspaces."""
    from ..admin.governance.admin_access_service import is_global_admin
    from .work_roles import active_human, workspace_humans

    user_id = run.responsible_user_id
    if not user_id or await active_human(db, user_id) is None:
        return ()
    if user_id in await workspace_humans(db, run.project_id):
        return (user_id,)
    if run.responsible_source == SOURCE_TAKEN_OVER and await is_global_admin(db, user_id):
        return (user_id,)
    return ()


async def responsible_view(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    """``{user_id, display_name, source}`` for the run card, the run list and the phone; None when nobody is."""
    if not run.responsible_user_id:
        return None
    person = await db.get(User, run.responsible_user_id)
    name = (person.display_name or person.username) if person is not None else None
    return {"user_id": run.responsible_user_id, "display_name": name, "source": run.responsible_source}


async def may_take_over(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    """Write access to the run (requester, Work item owner, platform admin), as ``access.run_access`` decides."""
    from ..admin.governance.admin_access_service import is_global_admin
    from .access import run_access

    return await run_access(db, run, user) == "write" or await is_global_admin(db, user.id)


async def may_self_take_over(db: AsyncSession, run: WorkflowRun, user: User) -> bool:
    """The responsible person by their own start (``requester``) is a platform admin outside the run's Workspace:
    only an explicit takeover makes them a decider (``responsible_decider``)."""
    from ..admin.governance.admin_access_service import is_global_admin
    from .work_roles import workspace_humans

    if not is_responsible(run, user) or run.responsible_source != SOURCE_REQUESTER:
        return False
    return user.id not in await workspace_humans(db, run.project_id) and await is_global_admin(db, user.id)


async def take_over_action(db: AsyncSession, run: WorkflowRun, user: User | None) -> dict[str, Any] | None:
    """The ``take_over`` a person with write access is offered: anyone not yet responsible, or a self-take-over."""
    if user is None:
        return None
    if not is_responsible(run, user):
        return dict(TAKE_OVER_ACTION)
    return dict(SELF_TAKE_OVER_ACTION) if await may_self_take_over(db, run, user) else None


async def take_over(db: AsyncSession, run: WorkflowRun, *, user: User) -> WorkflowRun:
    """``user`` becomes the run's responsible person (``taken_over``): audited, a run event, both people nudged."""
    from ..attention.stream import nudge_after_commit

    if run.status not in ACTIVE_STATUSES:
        raise WorkflowRunError("run_finished", "The run has ended; there is nothing to take over.", 409)
    if not await may_take_over(db, run, user):
        raise WorkflowRunError("take_over_not_permitted", "Only the requester, the Work item owner or an admin "
                                                          "takes this run over.", 403)
    if is_responsible(run, user) and not await may_self_take_over(db, run, user):
        raise WorkflowRunError("already_responsible", "You are already responsible for this run.", 409)
    run = await lock_run(db, run)
    previous, previous_source = run.responsible_user_id, run.responsible_source
    run.responsible_user_id, run.responsible_source = user.id, SOURCE_TAKEN_OVER
    record_event(db, run, EVENT_TAKEN_OVER, node_id=run.current_node_id, actor_id=user.id,
                 detail={"from": previous, "from_source": previous_source, "to": user.id})
    db.add(AuditLog(user_id=user.id, action=AUDIT_TAKEN_OVER, resource_type="workflow_run", resource_id=run.id,
                    details={"run_id": run.id, "previous_responsible_user_id": previous,
                             "previous_source": previous_source, "responsible_user_id": user.id}))
    if previous and previous != run.requested_by:
        nudge_after_commit(db, previous, run_id=run.id, event=EVENT_TAKEN_OVER)
    return run


__all__ = [
    "ACTION_TAKE_OVER",
    "AUDIT_TAKEN_OVER",
    "EVENT_TAKEN_OVER",
    "RESPONSIBLE_CHAIN",
    "SOURCES",
    "SOURCE_ACCEPTED",
    "SOURCE_ASSIGNEE",
    "SOURCE_REPORTER",
    "SOURCE_REQUESTER",
    "SELF_TAKE_OVER_ACTION",
    "SOURCE_TAKEN_OVER",
    "TAKE_OVER_ACTION",
    "initial_responsible",
    "is_responsible",
    "may_self_take_over",
    "may_take_over",
    "responsible_decider",
    "responsible_for",
    "responsible_view",
    "take_over",
    "take_over_action",
]
