"""One authoritative interactive-human decider policy for Workflow nodes.

Resolve only authored policies, never tool rights or execution identities. The run's responsible person
(``responsible``) is an additional decider of a node without an authored policy and of a
``requester`` node only. Callers must retain payload-hash, four-eyes, permissions and lifecycle checks. Final
authorization locks the Run and re-derives its current pinned node; it does not trust a UI's candidate list or
stale node.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AuditLog, User, WorkflowRun
from ...models.runtime.secure_work import WorkItem
from ..linked_accounts.resolution import account_names
from ..work_role_model.seeds import WORK_ROLE_KEYS
from .graph import PhasedNode, graph_for_run
from .records import WorkflowRunError
from .responsible import responsible_decider
from .work_roles import lock_actor_membership, work_role_members, workspace_humans

FUNCTION_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
# The product owner's decisions (readiness, spec interview, review, acceptance, publication): with role-based tools
# on, the decider must also hold the function ``decide_as_po``.
PO_SUBJECTS = frozenset({"decisions", "readiness", "interview", "functional_acceptance", "publication"})
PO_FUNCTION = "decide_as_po"


@dataclass(frozen=True, slots=True)
class DeciderResolution:
    policy: str
    user_ids: tuple[str, ...]
    reason: str = ""
    deputy_user_ids: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.user_ids) and not self.reason

    def allows(self, user_id: str) -> bool:
        return self.configured and user_id in self.user_ids


def validate_decider_config(config: dict[str, Any]) -> str:
    """Closed authored syntax; empty, unknown or unimplemented policies never fall back to requester."""
    for key in ("decider", "deputy"):
        if key not in config:
            continue
        value = config[key]
        if not isinstance(value, str):
            return f"{key} must be a closed decider value"
        if value.startswith("role:") and value[5:] in WORK_ROLE_KEYS:
            continue
        # ``function:<key>``: whoever holds the work-role function in the Workspace, e.g.
        # ``function:decide_as_po`` — the product owner is a function, not a role name.
        if value.startswith("function:") and FUNCTION_KEY.match(value[9:]):
            continue
        # ``spec_origin``: the exact human who confirmed the accepted spec; authored only, never a default.
        if key == "decider" and value in ("requester", "item_owner", "handoff_owner", "spec_origin"):
            continue
        return f"{key} is not a supported decider value"
    return ""


def _with(ids: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    return ids + tuple(user_id for user_id in extra if user_id not in ids)


async def _item_owner(db: AsyncSession, run: WorkflowRun, members: dict[str, User]) -> tuple[tuple[str, ...], str]:
    item = await db.get(WorkItem, run.work_item_id, populate_existing=True) if run.work_item_id else None
    if item is None or item.project_id != run.project_id:
        return (), "item_owner_unresolved"
    assignee = str(item.assignee or "").strip().lower()
    if not assignee:
        return (), "item_owner_unresolved"
    linked = await account_names(db, set(members))
    matches = tuple(sorted(user.id for user in members.values() if assignee in {
        str(user.username or "").lower(), str(user.email or "").lower(), *linked.get(user.id, set())}))
    return (matches, "") if len(matches) == 1 else ((), "item_owner_ambiguous" if matches else "item_owner_unresolved")


async def resolve_decider(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> DeciderResolution:
    """A node without an authored ``decider`` is a ``requester`` node: the shipped seeds author it explicitly."""
    invalid = validate_decider_config(node.config)
    policy = node.config.get("decider", "requester")
    if invalid:
        return DeciderResolution(str(policy), (), "decider_unresolved")
    deputy = node.config.get("deputy")
    deputy_ids = await work_role_members(db, run.project_id, deputy[5:]) if deputy else ()
    members = await workspace_humans(db, run.project_id)
    if policy == "requester":
        # An authored "requester" node also goes to the responsible person; role, item-owner,
        # handoff and spec-origin policies stay exactly as authored.
        ids = _with((run.requested_by,) if run.requested_by in members else (), await responsible_decider(db, run))
        reason = "" if ids else "requester_unresolved"
    elif policy == "item_owner":
        ids, reason = await _item_owner(db, run, members)
    elif policy.startswith("role:"):
        ids = await work_role_members(db, run.project_id, policy[5:])
        reason = "" if ids else "role_unresolved"
    elif policy.startswith("function:"):
        from ..work_role_model.effective import members_with

        ids = await members_with(db, run.project_id, function_key=policy[9:], user_ids=members)
        reason = "" if ids else "function_unresolved"
    elif policy == "handoff_owner":
        from .handoff.lifecycle import resolved_owner

        ids, reason = await resolved_owner(db, run)
    elif policy == "spec_origin":
        from .specification.origin import spec_origin

        ids, reason = await spec_origin(db, run, members)
    else:
        ids, reason = (), "handoff_owner_unresolved"
    return DeciderResolution(policy, ids, reason, deputy_ids)


async def po_function_refusal(db: AsyncSession, run: WorkflowRun, user: User) -> str | None:
    """Why ``user`` may not take the run's waiting product-owner decision, else ``None``.

    Only with the Workspace's role-based tools on; platform admins keep their access. The refusal names the setting
    and who can change it."""
    subject = str(dict(dict(run.node_state or {}).get("waiting") or {}).get("subject") or "")
    if subject not in PO_SUBJECTS:
        return None
    from ..work_role_model.effective import effective_permission

    grant = await effective_permission(db, user.id, run.project_id)
    if grant.has_function(PO_FUNCTION):
        return None
    return ("This is a product owner's decision: it needs a work role with the function 'Decide as product owner' "
            "in this Workspace. A Workspace admin can assign such a role (Workspace › Roles).")


async def may_decide(db: AsyncSession, run: WorkflowRun, node: PhasedNode, user: User) -> bool:
    if not (await resolve_decider(db, run, node)).allows(user.id):
        return False
    return await po_function_refusal(db, run, user) is None


async def require_node_decider(db: AsyncSession, run: WorkflowRun, user: User, *,
                               expected_node_id: str | None = None) -> DeciderResolution:
    """Final current-policy recheck under Run lock; no session/requester/runtime rewrite."""
    expected = expected_node_id or run.current_node_id
    # Root callers may already hold this lock. Populate to defeat a stale identity-map object.
    from .handoff.lifecycle import guard_receiver

    await guard_receiver(db, run)
    current = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == run.id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if current is None or current.status not in ("waiting", "paused", "running"):
        raise WorkflowRunError("decision_stale", "The run is no longer awaiting this decision.", 409)
    if current.current_node_id != expected:
        raise WorkflowRunError("decision_stale", "The run moved to another decision.", 409)
    node = (await graph_for_run(db, current)).nodes.get(str(current.current_node_id or ""))
    if node is None:
        raise WorkflowRunError("decider_unresolved", "The current decision node is not configured.", 409)
    resolution = await resolve_decider(db, current, node)
    if not resolution.configured:
        raise WorkflowRunError(
            "decider_unresolved", f"The human decider needs configuration ({resolution.reason}).", 409)
    if not resolution.allows(user.id):
        raise WorkflowRunError("not_decider", "Only the current node's resolved human decider may decide.", 403)
    await lock_actor_membership(db, current.project_id, user.id,
        role_key=resolution.policy[5:] if resolution.policy.startswith("role:") else None)
    # The initial view was only an offer. Authority is decided from fresh membership while held.
    resolution = await resolve_decider(db, current, node)
    if not resolution.allows(user.id):
        raise WorkflowRunError("not_decider", "The node's decider membership changed before this decision.", 403)
    po_refusal = await po_function_refusal(db, current, user)
    if po_refusal is not None:
        raise WorkflowRunError("po_function_required", po_refusal, 403)
    from .specification.origin import require_decider_spec_authority

    # A spec-bound run: the decider's OWN current source authority, never the owner's or the policy's.
    await require_decider_spec_authority(db, current, user)
    return resolution


def audit_decider_decision(db: AsyncSession, run: WorkflowRun, user: User, resolution: DeciderResolution,
                           *, node_id: str, payload_hash: str, decision_id: str) -> None:
    """Root calls only AFTER a successful, hash-bound decision with all governance checks intact."""
    db.add(AuditLog(user_id=user.id, action="workflow_decider.decision", resource_type="workflow_run",
        resource_id=run.id, details={"node_id": node_id, "policy": resolution.policy,
            "payload_hash": payload_hash, "decision_id": decision_id,
            "execution_user_id": run.requested_by}))


__all__ = ["DeciderResolution", "resolve_decider", "may_decide", "require_node_decider",
           "validate_decider_config", "audit_decider_decision"]
