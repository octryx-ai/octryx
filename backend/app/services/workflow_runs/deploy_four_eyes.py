"""Four-eyes before a deploy, enforced by structure and at runtime — never only a property of a seed."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, WorkflowRun

DEPLOY_ACTION = "deploy.run"
CONTEXT_KEY = "four_eyes"


def deploy_approves(graph: Any, approval_id: str | None, deploy_id: str) -> bool:
    from .graph import NODE_APPROVAL

    node = graph.nodes.get(approval_id or "")
    if node is None or node.kind != NODE_APPROVAL:
        return False
    return str(node.config.get("subject") or "") == "deploy" or any(
        edge.target == deploy_id and edge.when == "approved" for edge in graph.exits(node.id))


def deploy_approval_errors(graph: Any) -> list[dict[str, str]]:
    from .graph import NODE_PLATFORM_ACTION, NODE_START

    deploys = sorted(node.id for node in graph.nodes.values() if node.kind == NODE_PLATFORM_ACTION
                     and str(node.config.get("action") or "").strip() == DEPLOY_ACTION)
    starts = [node.id for node in graph.nodes.values() if node.kind == NODE_START]
    errors = []
    for deploy_id in deploys:
        seen, frontier = set(starts), list(starts)
        while frontier:  # walk from the start, never through an approval of this deploy
            node_id = frontier.pop()
            for edge in graph.exits(node_id):
                target = graph.nodes.get(edge.target)
                if target is None or target.id in seen or deploy_approves(graph, target.id, deploy_id):
                    continue
                seen.add(target.id)
                frontier.append(target.id)
        if deploy_id in seen:
            errors.append({"code": "deploy_without_four_eyes",
                           "message": f"Node '{deploy_id}' deploys on a path without its own approval: every path "
                                      f"to {DEPLOY_ACTION} passes an approval of the deploy (subject 'deploy', or "
                                      "the approval that leads straight to it)."})
    return errors


def record_approval(run: WorkflowRun, *, approval_id: str, approved_by: str | None, node_id: str | None) -> None:
    state = dict(run.node_state or {})
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {
        "approval_id": approval_id, "approved_by": approved_by, "node_id": node_id, "entry": state.get("entry")}}


async def deploy_approval_refusal(db: AsyncSession, run: WorkflowRun) -> str:
    context = dict(run.context or {})
    granted = dict(context.get(CONTEXT_KEY) or {})
    if not granted.get("approval_id"):
        return "a deploy needs a four-eyes approval decided in this pass of the run"
    if dict(context.get("deploy") or {}).get("approval_id") == granted["approval_id"]:
        return "this approval already started a deploy; a new deploy needs a new approval"
    from .graph import graph_for_run

    if not deploy_approves(await graph_for_run(db, run), granted.get("node_id"), run.current_node_id or ""):
        return "the approval of this pass is not the deploy's approval"
    from ..governance.four_eyes import FOUR_EYES_PASSING_STATUSES, decide_four_eyes

    approval = await db.get(Approval, str(granted["approval_id"]))
    if approval is None or approval.status != "approved" or not approval.approved_by:
        return "the deploy's approval is not decided approved"
    rule = await decide_four_eyes(db, run.requested_by, approval.approved_by, authors=[run.requested_by])
    if rule.status not in FOUR_EYES_PASSING_STATUSES:
        return "the deploy's approval does not pass the four-eyes rule (another person approves)"
    return ""


__all__ = ["CONTEXT_KEY", "DEPLOY_ACTION", "deploy_approval_errors", "deploy_approves", "deploy_approval_refusal",
           "record_approval"]
