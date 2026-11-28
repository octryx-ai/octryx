"""How often a failed check (gate, pipeline, CI) sends the work back to the agent: the Workspace's
``device_runs.check_attempts`` (default 3), one more bound in the engine's loop limit; then ``checks_failed``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .ci_return import CI_FAILED_CONDITION
from .graph import NODE_GATE, NODE_PLATFORM_ACTION, PhasedEdge, PhasedGraph
from .pipeline import ACTION as PIPELINE_ACTION
from .pipeline import STATE_RED
from .pipeline import state as pipeline_state

SETTING = "check_attempts"
MAX_OUTPUT_ITEMS = 10
MAX_DETAIL_CHARS = 400


def attempts_from(section: dict[str, Any] | None) -> int:
    from ..devices.device_runs_keys import DEFAULTS

    raw = dict(section or {}).get(SETTING)
    return raw if type(raw) is int and raw >= 1 else DEFAULTS[SETTING]


def leaves_a_check(graph: PhasedGraph, edge: PhasedEdge) -> bool:
    if edge.when == CI_FAILED_CONDITION:
        return True
    source = graph.nodes.get(edge.source)
    if source is None:
        return False
    return source.kind == NODE_GATE or (
        source.kind == NODE_PLATFORM_ACTION and str(dict(source.config or {}).get("action") or "") == PIPELINE_ACTION)


async def check_attempt_cap(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, edge: PhasedEdge) -> int | None:
    from ..agent_gateway.policy import load_workspace_policy
    from ..devices.device_runs_keys import device_runs_section
    from .size_class.loops import RAISED_KEY

    if not leaves_a_check(graph, edge):
        return None
    # A person who granted more rounds at the pause decides from there.
    if dict(dict(run.loop_counters or {}).get(edge.id) or {}).get(RAISED_KEY):
        return None
    loaded = await load_workspace_policy(db, run.project_id)
    return attempts_from(device_runs_section(loaded.policy.raw) if loaded.policy is not None else None)


def _short(value: Any) -> str:
    return str(value or "").strip()[:MAX_DETAIL_CHARS]


def failed_checks(run: WorkflowRun, source: str) -> list[dict[str, Any]]:
    from ..workflow_checks.library import FAILED
    from .pipeline_results import _failed_line, _green

    gate = dict(dict(run.gate_results or {}).get(source) or {})
    failed = [{"check": str(item.get("type") or ""), "detail": _short(item.get("detail"))}
              for item in gate.get("results") or [] if isinstance(item, dict) and item.get("outcome") == FAILED]
    pipeline = pipeline_state(run)
    if pipeline.get("node_id") == source and pipeline.get("state") == STATE_RED:
        failed += [{"check": "pipeline", "detail": _short(_failed_line(item)),
                    "output_tail": str(item.get("output_tail") or "")[-MAX_DETAIL_CHARS:]}
                   for item in pipeline.get("results") or [] if isinstance(item, dict) and not _green(item)]
    ci = dict(dict(run.context or {}).get("ci") or {})
    if not failed and ci.get("state") == "failed":
        failed.append({"check": "ci", "detail": _short(ci.get("summary") or ci.get("url"))})
    return failed[:MAX_OUTPUT_ITEMS]


async def loop_bound(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, edge: PhasedEdge,
                     limit: int) -> tuple[int, int | None]:
    cap = await check_attempt_cap(db, run, graph, edge)
    return (limit if cap is None else min(limit, cap)), cap


def loop_pause(run: WorkflowRun, edge: PhasedEdge, used: int, limit: int, cap: int | None,
               last_failure: Any) -> tuple[str, dict[str, Any]]:
    from .states import PAUSE_CHECKS_FAILED, PAUSE_LOOP_LIMIT

    red = cap is not None and used >= cap
    return PAUSE_CHECKS_FAILED if red else PAUSE_LOOP_LIMIT, {
        "edge_id": edge.id, "used": used, "limit": limit, **({"last_failure": last_failure} if last_failure else {}),
        **({"checks": failed_checks(run, edge.source)} if red else {})}
