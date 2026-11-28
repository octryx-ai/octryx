"""A push or pull request only for the tree the run's CI pipeline ran green on."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from . import safe_git
from .graph import EDGE_NEXT, FAILED, NODE_PLATFORM_ACTION, PhasedEdge, PhasedGraph, PhasedNode
from .platform import catalog
from .platform.dispatch import ToolOutcome
from .records import record_event
from .states import PAUSE_PIPELINE_NOT_FOR_HEAD

ROUTE = "pipeline_not_for_head"
RERUN_KEY = "pipeline_head_rerun"  # context: the pipeline node to re-enter, set by the guard, read by the engine
CLASS_PIPELINE_NOT_FOR_HEAD = "pipeline_not_for_head"
EVENT = "pipeline_not_for_head"
GUARDED = frozenset({catalog.SCM_PUSH, catalog.SCM_OPEN_PR})
HINT = ("The platform pushes and opens a pull request only for the tree its CI pipeline ran green on. Continue "
        "re-runs the pipeline on the run's current change; if it stays on another tree, the device's working "
        "folder is not the change the server holds (check the folder for changes made outside the run).")


async def server_tree(run: WorkflowRun) -> str:
    context = dict(run.context or {})
    change = dict(context.get("device_change") or {})
    local = str(context.get("local_path") or "")
    patch = str(change.get("patch") or "")
    if not local or change.get("base_unavailable") or change.get("truncated") or not patch.strip():
        return ""
    return await safe_git.patch_tree(local, str(change.get("base") or context.get("base_sha") or ""), patch)


async def binding(run: WorkflowRun, reported: Any) -> dict[str, Any]:
    device = str(reported).strip() if isinstance(reported, str) else ""
    tree = await server_tree(run)
    mismatch = bool(tree and device and device != tree)
    return {"tree": "" if mismatch else tree, **({"device_tree": device} if device else {}),
            **({"tree_mismatch": True} if mismatch else {})}


def pipeline_nodes(graph: PhasedGraph) -> list[str]:
    nodes = dict(getattr(graph, "nodes", None) or {})
    order = [node_id for node_id in getattr(graph, "order", None) or [] if node_id in nodes] or list(nodes)
    return [node_id for node_id in order if nodes[node_id].kind == NODE_PLATFORM_ACTION
            and str(nodes[node_id].config.get("action") or "") == catalog.PIPELINE_RUN]


async def _head_tree(run: WorkflowRun, key: str) -> str:
    context = dict(run.context or {})
    if key == catalog.SCM_OPEN_PR and context.get("head_sha") and context.get("local_path"):
        pushed = await safe_git.tree_of(str(context["local_path"]), str(context["head_sha"]))
        if pushed:
            return pushed
    return str(dict(context.get("review") or {}).get("tree") or "")


def _why(current: dict[str, Any], head: str) -> str:
    state = str(current.get("state") or "")
    if not current:
        return "the CI pipeline has not run for this change"
    if state != "green":
        return f"the last CI pipeline is {state or 'unknown'}, not green"
    if current.get("tree_mismatch"):
        return ("the CI pipeline ran on a working folder that is not the change the server holds "
                f"(device tree {str(current.get('device_tree') or '')[:12]})")
    if not current.get("tree"):
        return "the green CI pipeline is bound to no tree (the server held no change for it)"
    if not head:
        return "the tree to push is unknown"
    return (f"the green CI pipeline ran on tree {str(current['tree'])[:12]}, the head to push is tree "
            f"{head[:12]}")


async def _applies(db: AsyncSession, run: WorkflowRun, current: dict[str, Any]) -> bool:
    from .pipeline import commands_for, environment_file_for
    from .workspace.preparation import RUNTIME_SERVER, runtime_of

    if current.get("state") == "skipped":
        return False
    if current:
        return True
    declared = await environment_file_for(db, run) is not None or bool((await commands_for(db, run))[0])
    return declared and await runtime_of(db, run) != RUNTIME_SERVER


async def guard(db: AsyncSession, run: WorkflowRun, key: str,
                node: PhasedNode | None) -> tuple[ToolOutcome, str] | None:
    from .graph import graph_for_run
    from .pipeline import state

    if key not in GUARDED:
        return None
    nodes = pipeline_nodes(await graph_for_run(db, run))
    current = state(run)
    if not nodes or not await _applies(db, run, current):
        return None
    head = await _head_tree(run, key)
    if current.get("state") == "green" and current.get("tree") and current.get("tree") == head:
        return None
    why = _why(current, head)
    facts = {"action": key, "reason": why, "pipeline_state": current.get("state"),
             "pipeline_tree": current.get("tree") or None, "head_tree": head or None}
    target = str(current.get("node_id") or "") if current.get("node_id") in nodes else nodes[0]
    outcome = ToolOutcome(FAILED, facts, f"{key} refused: {why}", failure_class=CLASS_PIPELINE_NOT_FOR_HEAD)
    if node is None:  # a session's request: refused, the run's own push node checks again
        record_event(db, run, EVENT, node_id=run.current_node_id, detail={**facts, "decision": "refused"})
        return outcome, FAILED
    if not current.get("head_rerun"):
        run.context = {**dict(run.context or {}), RERUN_KEY: {"node_id": target, "from": node.id, "reason": why,
                                                              "at": utc_now().isoformat()}}
        record_event(db, run, EVENT, node_id=node.id, detail={**facts, "decision": "rerun", "pipeline_node": target})
        return outcome, ROUTE
    from .limits import pause_run
    from .platform_actions import WAIT

    record_event(db, run, EVENT, node_id=node.id, detail={**facts, "decision": "paused"})
    await pause_run(db, run, reason=PAUSE_PIPELINE_NOT_FOR_HEAD, actor_id=None, detail={
        **facts, "message": f"{node.title or node.id} did not run: {why}.", "hint": HINT,
        "resume": {"kind": "restart", "node_id": target}})
    return outcome, WAIT


def rerun_edge(run: WorkflowRun | None, graph: PhasedGraph, node: PhasedNode) -> PhasedEdge | None:
    target = str(dict(dict(getattr(run, "context", None) or {}).get(RERUN_KEY) or {}).get("node_id") or "")
    if target not in graph.nodes:
        return None
    return PhasedEdge(id=f"{RERUN_KEY}:{node.id}", source=node.id, target=target, kind=EDGE_NEXT, when=ROUTE,
                      max_iterations=None, title="Re-run the CI pipeline for the head")


def take_rerun(run: WorkflowRun) -> bool:
    context = dict(run.context or {})
    if RERUN_KEY not in context:
        return False
    context.pop(RERUN_KEY)
    run.context = context
    return True


__all__ = ["CLASS_PIPELINE_NOT_FOR_HEAD", "EVENT", "HINT", "RERUN_KEY", "ROUTE", "binding", "guard",
           "pipeline_nodes", "rerun_edge", "server_tree", "take_rerun"]
