"""The run's CI pipeline: the repository's declared test commands, run without an agent."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .graph import SUCCEEDED, PhasedNode
from .platform.dispatch import ToolOutcome
from .records import record_event

ACTION = "pipeline.run"
CONTEXT_KEY = "pipeline"
STATE_PENDING, STATE_GREEN, STATE_RED = "pending", "green", "red"
EVENT_REPORTED = "pipeline_reported"


def state(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {})


def _set(run: WorkflowRun, value: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), CONTEXT_KEY: value}


async def commands_for(db: AsyncSession, run: WorkflowRun) -> tuple[list[str], list[str], str]:
    from .workspace.spec import environment_for_run

    environment = dict(await environment_for_run(db, run) or {})
    test, lint, system = (str(environment.get(key) or "").strip() for key in ("test", "lint", "system_test"))
    return [command for command in (test, lint, system) if command], [
        str(item) for item in environment.get("path") or []], system


async def environment_file_for(db: AsyncSession, run: WorkflowRun) -> dict[str, str] | None:
    from .platform.repo_ref import _record, _setup, parse_repository
    from .workspace.run_app import record_default, run_environment_file
    from .workspace.spec import app_folder, environment_file_of

    ref = parse_repository(run.repository)
    pointer = run_environment_file(run) or record_default(
        run, environment_file_of(_setup(await _record(db, run, ref))) if ref is not None else None)
    return {"file": pointer, "app_folder": app_folder(pointer)} if pointer else None


async def browser_for(db: AsyncSession, run: WorkflowRun) -> str:
    from .workspace.spec import environment_for_run

    try:
        return str(dict(await environment_for_run(db, run) or {}).get("browser") or "")
    except Exception:  # noqa: BLE001 - the device default (the installed Chrome) applies without an answer
        return ""


async def start(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> tuple[ToolOutcome, str]:
    from .pipeline_head import take_rerun
    from .platform_actions import WAIT
    from .workspace.preparation import RUNTIME_SERVER, runtime_of

    head_rerun = take_rerun(run)
    pointer = await environment_file_for(db, run)
    commands, path, system_command = ([], [], "") if pointer else await commands_for(db, run)
    from .size_class.pipeline_scope import runs_system_test

    system_test = runs_system_test(run)
    if not system_test and system_command:
        commands = [command for command in commands if command != system_command]
    if not commands and not pointer:
        return ToolOutcome(SUCCEEDED, {"skipped": "the repository declares no test command"}), SUCCEEDED
    if await runtime_of(db, run) == RUNTIME_SERVER:
        # A server run has no pipeline runner yet (the server never runs repository code): the step is skipped and
        # says so; the building phase's own test gates stand. Never a failure that loops the run.
        _set(run, {"state": "skipped", "node_id": node.id, "reason": "no pipeline runner for a server run yet",
                   "commands": commands, "at": utc_now().isoformat()})
        record_event(db, run, EVENT_REPORTED, node_id=node.id, detail={"state": "skipped",
                                                                       "reason": "no pipeline runner on the server"})
        return ToolOutcome(SUCCEEDED, {"skipped": "no pipeline runner for a server run yet"}), SUCCEEDED
    browser = "" if pointer else await browser_for(db, run)
    from .octryx.code_limits import phase_style

    # the pipeline also judges the whole change against the installation's code style, on the
    # device's counts against the run's base, whatever the phases' own Stop checks saw.
    style = await phase_style(db, run, "change")
    base = str(dict(run.context or {}).get("base_sha") or "")
    reruns = await _rerun_specs(db, run)
    from ..engineering_knowledge.stacks import all_report_args, all_report_env
    from .red_on_base import request as red_on_base

    # The confirmed tests once more on the base commit (size class ``red_on_base``), named from the app folder.
    proof = red_on_base(run, str((pointer or {}).get("app_folder") or "."))
    _set(run, {"state": STATE_PENDING, "node_id": node.id, "entry": dict(run.node_state or {}).get("entry"),
               **({"code_style": style, "base": base} if style and base else {}),
               **({"reruns": reruns} if reruns else {}),
               **({"red_on_base": proof} if proof else {}),
               "report_env": all_report_env(), "report_args": all_report_args(),
               "commands": commands, "path": path, **({"browser": browser} if browser else {}),
               **({"environment_file": pointer} if pointer else {}),
               **({"head_rerun": True} if head_rerun else {}), **({} if system_test else {"system_test": False}),
               "at": utc_now().isoformat()})
    from .octryx.continuation import runtime_step_entered

    await runtime_step_entered(db, run, node)
    return ToolOutcome("waiting", {"commands": commands, **({"environment_file": pointer} if pointer else {})}), WAIT


def follows(graph: Any, node_id: str, environment: Any) -> bool:
    # A review, confirmation or other node in between ends the walk: what stands before it is judged by its own Stop.
    from .graph import EDGE_LOOP, NODE_PARALLEL, NODE_PHASE, NODE_PLATFORM_ACTION

    environment = environment if isinstance(environment, dict) else {}
    if not environment.get("environment_file") and not any(
            str(environment.get(key) or "").strip() for key in ("test", "system_test")):
        return False
    nodes = dict(getattr(graph, "nodes", None) or {})
    edges = [edge for edge in getattr(graph, "edges", None) or [] if getattr(edge, "kind", None) != EDGE_LOOP]
    seen, frontier = {node_id}, [node_id]
    while frontier:
        source = frontier.pop()
        for edge in edges:
            target = nodes.get(edge.target) if edge.source == source else None
            if target is None or edge.target in seen:
                continue
            if target.kind == NODE_PLATFORM_ACTION and target.config.get("action") == ACTION:
                return True
            if target.kind in (NODE_PHASE, NODE_PARALLEL):  # an item's Stop is advisory like a phase's
                seen.add(edge.target)
                frontier.append(edge.target)
    return False


def contract_view(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    if current.get("state") != STATE_PENDING:
        return None
    from .workspace.contract_pin import view as pin_view

    # report_env and report_args must be in the view, or the device never writes the per-test report.
    optional = ("browser", "environment_file", "code_style", "base", "reruns", "red_on_base", "report_env",
                "report_args")
    found = {key: current.get(key) for key in ("node_id", "entry", "commands", "path", *optional)
             if key not in optional or current.get(key)}
    if current.get("system_test") is False:
        found["system_test"] = False
    from .build_cache import view as build_view

    found.update(build_view())
    # The run's pinned environment file (``workspace.contract_pin``): the device runs it, not the tree's.
    return {**found, "environment_pin": pinned} if (pinned := pin_view(run)) else found


async def _rerun_specs(db: AsyncSession, run: WorkflowRun) -> list[dict[str, Any]]:
    from ...models import Project
    from ..engineering_knowledge.stacks import for_project, rerun_specs

    project = await db.get(Project, run.project_id) if run.project_id else None
    return rerun_specs(await for_project(db, project))


def run_view(run: WorkflowRun) -> dict[str, Any] | None:
    current = state(run)
    if not current:
        return None
    return {"state": current.get("state"), "node_id": current.get("node_id"), "commands": current.get("commands"),
            "reported_at": current.get("reported_at"), "audit": current.get("audit"),
            **({"environment_file": current["environment_file"]} if current.get("environment_file") else {})}


__all__ = ["ACTION", "CONTEXT_KEY", "commands_for", "contract_view", "environment_file_for", "follows", "run_view",
           "start", "state"]
