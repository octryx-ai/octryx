"""The run's CI pipeline: the repository's declared test commands, run without an agent.

The screenshots come from the CI run that already uses Playwright, and the pipeline can run on the server or
locally. The building agent says its tests are green; the pipeline runs them itself,
like CI, on the run's change, and keeps what it saw: per command the exit code, the duration, the end of the output
and every test of its JUnit report (``tests`` of the run, source ``pipeline``, one result per test id), and the system
tests' screenshots for the review (``review.screens``, stored under this node).

**The single source of truth for "tests green" and "task proven"** (benchmark runs showed 34 Stop refusals in 7 stories
over how the model ran its tests, 5 human interventions, 3 hotfixes for proof detection, the agent stopping "because the
stop hook keeps blocking"). Green needs every declared command green **and** every task of the run's task list proven:
its named proof test passed in this pipeline. Then the tasks are ``done`` (``task_status.after_pipeline``) and the run
goes on to the review (``succeeded``). Otherwise red routes ``failed`` back to the building agent, whose contract gets
the failing commands, the failing test ids and the tasks without proof (``failure_for_agent``). A building phase
followed by this step, directly or after further phases (:func:`follows`), does not police at Stop how the model ran its
tests (``octryx/stop``).

**Flaky tests.** Without this,
``test_port_in_use_exits_3`` went red, green, red without a code change; each red sent the story back to the agent,
whose fix rounds then broke other tests. So the device runs a red pytest command once more with only its failed tests
(``octryx-claude`` ``pipeline``: ``rerun``). A test that failed and then passed with no change in between is
**flaky**: the first time a test of this run is flaky it is not counted as a failure of the story, the pipeline is
green and says so (``flaky`` in the report, the event and the step's reason). The same test flaky again in a later
pass of the run counts as red (``flaky_again``): then the test itself is the story's defect, and the agent is told
to make it deterministic. Every flaky test of the run is kept in ``pipeline_flaky`` (test id → times).

A device run: the platform action waits (``WAIT``) and the next device turn's launcher runs the commands in the run's
folder before the agent starts (``octryx-claude`` ``pipeline``), outside Claude Code's sandbox, then reports
``POST /sessions/pipeline``. The server does not run repository code (``execution_runtime.foreign_build_guard``):
a server run has no pipeline runner yet and the step says so instead of passing.

**Declared in the repository**: when the run's repository record names an
``environment_file`` (``workspace.spec``), the server sends only that pointer (``environment_file``: the file and its
app folder); the device reads the file in the run's folder, validates it like a declaration on the record and runs
exactly its ``test`` / ``system_test`` in the app folder. The report names the file, its SHA-256, the commands and the
commit; the server validates the reported environment again and judges only those commands. A missing or invalid file,
or a failed setup, is red with what to do (``failure_for_agent``: ``environment_file``), never a skipped test.

**Audit**: every report's ``audit`` (pipeline state, event, run view) says which commands ran, from which declaration
(the file and its hash, or the repository record) and on which commit and tree.

**Bound to a tree**: the report records the tree the pipeline ran on, computed by
the server from the change it holds and cross-checked with the tree the device reports (``pipeline_head``); a push
or pull request goes out only for the tree of the last green pipeline.
"""

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


async def commands_for(db: AsyncSession, run: WorkflowRun) -> tuple[list[str], list[str]]:
    """``(commands, path)``: the declared unit test and system test commands, in that order, and the declared
    ``path`` directories (folder-relative) put first on ``PATH``."""
    from .workspace.spec import environment_for_run

    environment = dict(await environment_for_run(db, run) or {})
    commands = [str(environment.get(key) or "").strip() for key in ("test", "system_test")]
    return [command for command in commands if command], [str(item) for item in environment.get("path") or []]


async def environment_file_for(db: AsyncSession, run: WorkflowRun) -> dict[str, str] | None:
    """``{file, app_folder}`` of the run's environment file (its app's, else the repository record's), else ``None``."""
    from .platform.repo_ref import _record, _setup, parse_repository
    from .workspace.run_app import record_default, run_environment_file
    from .workspace.spec import app_folder, environment_file_of

    ref = parse_repository(run.repository)
    pointer = run_environment_file(run) or record_default(
        run, environment_file_of(_setup(await _record(db, run, ref))) if ref is not None else None)
    return {"file": pointer, "app_folder": app_folder(pointer)} if pointer else None


async def browser_for(db: AsyncSession, run: WorkflowRun) -> str:
    """The repository's declared browser (``chrome`` / ``chromium``); ``""`` keeps the device default (Chrome)."""
    from .workspace.spec import environment_for_run

    try:
        return str(dict(await environment_for_run(db, run) or {}).get("browser") or "")
    except Exception:  # noqa: BLE001 - the device default (the installed Chrome) applies without an answer
        return ""


async def start(db: AsyncSession, run: WorkflowRun, node: PhasedNode) -> tuple[ToolOutcome, str]:
    """The node's ``(outcome, route)``; ``WAIT`` while the device runs the pipeline."""
    from .pipeline_head import take_rerun
    from .platform_actions import WAIT
    from .workspace.preparation import RUNTIME_SERVER, runtime_of

    head_rerun = take_rerun(run)  # the push found no green pipeline for its tree and sent the run back here
    pointer = await environment_file_for(db, run)
    commands, path = ([], []) if pointer else await commands_for(db, run)
    from .size_class.pipeline_scope import runs_system_test

    system_test = runs_system_test(run)  # the class may leave the system test out (``pipeline_scope``)
    if not system_test and commands:
        commands = commands[:1] if len(commands) > 1 else commands
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
    browser = "" if pointer else await browser_for(db, run)  # the file's own browser, read by the device
    from .octryx.code_limits import phase_style

    # the pipeline also judges the whole change against the installation's code style, on the
    # device's counts against the run's base, whatever the phases' own Stop checks saw.
    style = await phase_style(db, run, "change")
    base = str(dict(run.context or {}).get("base_sha") or "")
    reruns = await _rerun_specs(db, run)
    from ..engineering_knowledge.stacks import all_report_env
    from .red_on_base import request as red_on_base

    # The confirmed tests once more on the base commit (size class ``red_on_base``), named from the app folder.
    proof = red_on_base(run, str((pointer or {}).get("app_folder") or "."))
    _set(run, {"state": STATE_PENDING, "node_id": node.id, "entry": dict(run.node_state or {}).get("entry"),
               **({"code_style": style, "base": base} if style and base else {}),
               **({"reruns": reruns} if reruns else {}),
               **({"red_on_base": proof} if proof else {}),
               "report_env": all_report_env(),  # each test's result from the platform's own report (stacks.json)
               "commands": commands, "path": path, **({"browser": browser} if browser else {}),
               **({"environment_file": pointer} if pointer else {}),
               **({"head_rerun": True} if head_rerun else {}), **({} if system_test else {"system_test": False}),
               "at": utc_now().isoformat()})
    from .octryx.continuation import runtime_step_entered

    await runtime_step_entered(db, run, node)
    return ToolOutcome("waiting", {"commands": commands, **({"environment_file": pointer} if pointer else {})}), WAIT


def follows(graph: Any, node_id: str, environment: Any) -> bool:
    """Whether a pipeline step follows the phase ``node_id`` and the repository declares a command for it to run:
    then the pipeline, not the phase's Stop, judges the tests and the task proofs. The step may come directly or
    after further phases (team delivery: backend, frontend and tests are phases one after the other
    and only the last one is followed directly by the pipeline; the earlier ones' Stops would otherwise refuse until
    tests the test phase writes later were green). A ``parallel_work`` node counts like a phase: the coordinator's
    plan and its items are judged by the pipeline after it (teamwork). A review, a confirmation or any
    other node in between ends the walk: what stands before it is judged by the phase's own Stop. A workflow without
    the step, or a repository without a declared command (the step is skipped), keeps the Stop's own checks."""
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
    """The ``pipeline`` part of the run contract while the device has to run it."""
    current = state(run)
    if current.get("state") != STATE_PENDING:
        return None
    from .workspace.contract_pin import view as pin_view

    # report_env: without it in the view the device never wrote the per-test report.
    optional = ("browser", "environment_file", "code_style", "base", "reruns", "red_on_base", "report_env")
    found = {key: current.get(key) for key in ("node_id", "entry", "commands", "path", *optional)
             if key not in optional or current.get(key)}
    if current.get("system_test") is False:
        found["system_test"] = False  # the class leaves the environment file's system test out (pipeline_scope)
    from .build_cache import view as build_view

    found.update(build_view())  # a build the device made for the same inputs is reused (stacks.json)
    # The run's pinned environment file (``workspace.contract_pin``): the device runs it, not the tree's.
    return {**found, "environment_pin": pinned} if (pinned := pin_view(run)) else found


async def _rerun_specs(db: AsyncSession, run: WorkflowRun) -> list[dict[str, Any]]:
    """How the device re-runs a red non-pytest runner's failed tests (stack data ``test_runner.rerun``; pytest has
    its own plugin)."""
    from ...models import Project
    from ..engineering_knowledge.stacks import for_project, rerun_specs

    project = await db.get(Project, run.project_id) if run.project_id else None
    return rerun_specs(await for_project(db, project))


def run_view(run: WorkflowRun) -> dict[str, Any] | None:
    """The pipeline on the run view: its state and the audit of its last report (commands, declaration, commit)."""
    current = state(run)
    if not current:
        return None
    return {"state": current.get("state"), "node_id": current.get("node_id"), "commands": current.get("commands"),
            "reported_at": current.get("reported_at"), "audit": current.get("audit"),
            **({"environment_file": current["environment_file"]} if current.get("environment_file") else {})}


__all__ = ["ACTION", "CONTEXT_KEY", "commands_for", "contract_view", "environment_file_for", "follows", "run_view",
           "start", "state"]
