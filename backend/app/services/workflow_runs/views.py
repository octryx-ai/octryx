"""What the chat banner, the Work item and Observability show of a run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun, WorkflowRunSession
from ...models.runtime.secure_work import WorkItem
from ...time_utils import ensure_utc
from .failure import failure_view
from .octryx.seat_fallback import fallback_view as seat_fallback_view
from .responsible import responsible_view
from .run_card_parts import model_usage, spec_studio_summary, task_list_view
from .run_engine import run_engine_routes
from .run_notices import follow_up_failed, open_findings_view, reviewer_notice
from .teamwork.views import work_view

# The kinds that count as a phase of the run ("Phase n/m"): an agent phase and a Parallel work box, which does a
# phase's work with several agents.
STEP_KINDS = frozenset({"phase", "parallel_work"})


def _iso(value: Any) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


async def run_nodes(db: AsyncSession, run: WorkflowRun, *, user: Any = None) -> list[dict[str, Any]]:
    from .fragments.provenance import is_platform_admin, reader_fragment
    from .graph import graph_for_run

    graph = await graph_for_run(db, run)
    admin = bool(graph.provenance) and await is_platform_admin(db, user)
    nodes = []
    for node in graph.ordered_nodes():
        item: dict[str, Any] = {"id": node.id, "title": node.title, "kind": node.kind}
        fragment = reader_fragment(graph.provenance.get(node.id), admin=admin)
        if fragment is not None:
            item["fragment"] = fragment
        nodes.append(item)
    return nodes


async def _work_item(db: AsyncSession, run: WorkflowRun) -> dict[str, Any] | None:
    item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
    if item is None:
        return None
    return {"id": item.id, "key": item.source_key, "title": item.title, "url": item.source_url,
            "state": item.work_state}


def _loops(run: WorkflowRun) -> list[dict[str, Any]]:
    loops = []
    for edge_id, counter in dict(run.loop_counters or {}).items():
        if isinstance(counter, dict):
            loops.append({"edge_id": edge_id, "title": str(counter.get("title") or edge_id),
                          "used": int(counter.get("used") or 0), "limit": int(counter.get("limit") or 0)})
    return loops


async def run_view(db: AsyncSession, run: WorkflowRun, *, access: str, user: Any = None) -> dict[str, Any]:
    nodes = await run_nodes(db, run, user=user)
    phases = [node for node in nodes if node["kind"] in STEP_KINDS]
    current = next((node for node in nodes if node["id"] == run.current_node_id), None)
    phase_index = next((index for index, node in enumerate(phases) if node["id"] == run.current_node_id), None)
    sessions = (await db.execute(
        select(WorkflowRunSession).where(WorkflowRunSession.run_id == run.id)
        .order_by(WorkflowRunSession.linked_at.asc())
    )).scalars().all()
    from .actions import available_actions
    from .documentation.publish_prove_state import publish_prove_view
    from .hands_on.step import run_view as hands_on_run_view
    from .pipeline import run_view as pipeline_run_view
    from .runtime_target.target import target_view
    from .specification.integration import projected_node_state
    from .triage_routing import routing_view
    from .workspace.preparation import contract_view

    projected_state = await projected_node_state(db, run, principal=user)
    from .run_list import workflow_titles

    return {
        **(await _run_state(db, run, nodes=nodes, phases=phases, current=current, phase_index=phase_index,
                            sessions=sessions, projected_state=projected_state, titles=workflow_titles,
                            routing_view=routing_view)),
        **(await _run_work(db, run, target_view=target_view, contract_view=contract_view,
                           pipeline_run_view=pipeline_run_view, hands_on_run_view=hands_on_run_view,
                           publish_prove_view=publish_prove_view)),
        "sessions": [
            {"session_id": item.session_id, "role": item.role, "runtime": item.runtime, "active": item.active,
             "linked_at": _iso(item.linked_at)}
            for item in sessions
        ],
        "requested_by": run.requested_by,
        "access": access,
        "actions": await available_actions(db, run, access=access, user=user),
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
        "completed_at": _iso(run.completed_at),
    }


async def _run_state(db: AsyncSession, run: WorkflowRun, *, nodes: list[dict[str, Any]], phases: list[dict[str, Any]],
                     current: dict[str, Any] | None, phase_index: int | None, sessions: Any,
                     projected_state: dict[str, Any], titles: Any, routing_view: Any) -> dict[str, Any]:
    return {
        "id": run.id,
        "title": run.title,
        "workflow_key": run.workflow_key,
        # The workflow's current display name from its definition: a name derived from the key goes stale.
        "workflow_title": (await titles(db, [run])).get(run.id),
        "workflow_kind": run.workflow_kind,
        "workflow_version": run.workflow_version,
        "project_id": run.project_id,
        "status": run.status,
        "waiting_kind": run.waiting_kind,
        "pause_reason": run.pause_reason,
        "outcome": run.outcome,
        "last_error": run.last_error,
        "current_node": current,
        "node_state": projected_state,
        "phase_position": {"index": phase_index + 1 if phase_index is not None else None, "total": len(phases)},
        "nodes": nodes,
        "loops": _loops(run),
        "limits": dict(run.limits or {}),
        "budget_usage": dict(run.budget_usage or {}),
        "model_usage": await model_usage(db, [item.session_id for item in sessions]),
        "gate": _latest_gate(run),
        "waiting": projected_state.get("waiting") if run.status == "waiting" else None,
        "pause": _pause(run),
        "failure": await failure_view(db, run),
        "stop": stop_view(run),
        "adopted": adopted_view(run),
        "work_item": await _work_item(db, run),
        "responsible": await responsible_view(db, run),
        "routing": routing_view(run),
    }


async def _run_work(db: AsyncSession, run: WorkflowRun, *, target_view: Any, contract_view: Any,
                    pipeline_run_view: Any, hands_on_run_view: Any, publish_prove_view: Any) -> dict[str, Any]:
    return {
        "ticket_key": run.ticket_key,
        "repository": run.repository,
        "branch": run.branch,
        "runtime_target": target_view(run),
        "preparation": contract_view(run),
        "pipeline": pipeline_run_view(run),
        "hands_on": hands_on_run_view(run),
        "pull_request": dict(run.pull_request or {}),
        "open_findings": open_findings_view(run),
        "spec_studio": spec_studio_summary(run),
        "task_list": task_list_view(run),
        "documentation": dict(dict(run.context or {}).get("documentation") or {}) or None,
        "publish_prove": publish_prove_view(run),
        # Exception: the requester is the PR author (the connection's account), so the SCM has them as no reviewer.
        "reviewer_notice": reviewer_notice(run),
        "work": work_view(run),
        # Started by a signed *test* alert: the card and every confirmation say so (no real incident).
        "test_alert": bool(dict(dict(run.context or {}).get("alert") or {}).get("test")),
        "sample": is_sample(run),
        **(await run_engine_routes(db, [run.id]))[run.id],
        "seat_fallback": seat_fallback_view(run),
    }


def _latest_gate(run: WorkflowRun) -> dict[str, Any] | None:
    from .review.artefact_projection import gate_detail

    results = dict(run.gate_results or {})
    if run.current_node_id in results:
        return gate_detail(results[run.current_node_id])
    dated = [item for item in results.values() if isinstance(item, dict)]
    return gate_detail(max(dated, key=lambda item: str(item.get("at") or ""), default=None))


def _pause(run: WorkflowRun) -> dict[str, Any] | None:
    if run.status != "paused":
        return None
    pause = dict(dict(run.node_state or {}).get("pause") or {})
    edge_id = str(pause.get("edge_id") or "")
    loop = next((item for item in _loops(run) if item["edge_id"] == edge_id), None)
    detail = str(pause.get("message") or "")
    if not detail and loop is not None:
        detail = f"{loop['title']} reached {loop['used']} of {loop['limit']} iterations."
    view = {"reason": str(run.pause_reason or ""), "detail": detail or "The run is paused.", "loop": loop,
            "cause": pause.get("cause"), "cause_rule": pause.get("cause_rule"),
            "code": str(pause.get("code") or "") or None,
            "loop_kind": pause.get("loop") if isinstance(pause.get("loop"), str) else None}
    if pause.get("action_node_id"):
        failure = dict(pause.get("failure") or {})
        view["failed_action"] = {"node_id": pause["action_node_id"], "action": pause.get("action"),
                                 "failure_class": pause.get("failure_class"), "reason": failure.get("reason"),
                                 "detail": dict(failure.get("detail") or {})}
    return view


def stop_view(run: WorkflowRun) -> dict[str, Any] | None:
    stop = dict(dict(run.context or {}).get("stop") or {})
    return {key: stop.get(key) for key in ("reason", "by", "at", "via", "node_id", "was")} if stop else None


def adopted_view(run: WorkflowRun) -> dict[str, Any]:
    context = dict(run.context or {})
    adopted: dict[str, Any] = {}
    if context.get("branch_adoption"):
        adopted["branch"] = dict(context["branch_adoption"])
    if context.get("ticket_adopted_from_run"):
        adopted["ticket"] = {"key": run.ticket_key, "from_run": context["ticket_adopted_from_run"]}
    plan = dict(context.get("change_plan") or {})
    if plan.get("adopted_from_run"):
        adopted["change_plan"] = {"id": plan.get("id"), "version": plan.get("version"),
                                  "from_run": plan["adopted_from_run"]}
    pr = dict(run.pull_request or {})
    if pr.get("adopted_from_run"):
        adopted["pull_request"] = {"id": pr.get("id"), "url": pr.get("url"), "from_run": pr["adopted_from_run"]}
    return adopted



def is_sample(run: Any) -> bool:
    return bool(dict(run.context or {}).get("sample_bundle"))


def run_row(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": run.id, "title": run.title, "workflow_key": run.workflow_key, "workflow_kind": run.workflow_kind,
        "status": run.status, "waiting_kind": run.waiting_kind, "pause_reason": run.pause_reason,
        "waiting_reason": dict(dict(run.node_state or {}).get("waiting") or {}).get("reason")
        if run.status == "waiting" else None,
        "outcome": run.outcome, "current_node_id": run.current_node_id, "work_item_id": run.work_item_id,
        "ticket_key": run.ticket_key, "project_id": run.project_id, "requested_by": run.requested_by,
        "repository": run.repository, "branch": run.branch,
        "stop_reason": (stop_view(run) or {}).get("reason"),
        "sample": is_sample(run),
        "follow_up_failed": follow_up_failed(run),
        "created_at": _iso(run.created_at), "updated_at": _iso(run.updated_at),
    }


__all__ = ["adopted_view", "run_nodes", "run_row", "run_view", "stop_view"]
