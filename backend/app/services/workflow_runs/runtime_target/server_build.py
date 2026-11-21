"""A run that builds or tests the repository never runs on the server.

The server would run the repository's own build code (Maven plugins, Gradle scripts, npm lifecycle scripts, test
fixtures) inside the API pod (``execution_runtime.foreign_build_guard``). So a run whose runtime is the server is
refused before it exists when its workflow DECLARES a build or test step, with ``server_build_not_allowed`` and one
plain message; on a device or an octryx-claude terminal it runs (the build runs on the person's own machine).

What counts as declared (``build_steps``), per phased node:

- a test/lint check: ``test_command_passed``, ``tests_red``, ``tests_green``, ``confirmed_tests_intact``,
  ``reproduces``, ``lint_passed`` (the lint check runs the declared lint command; the TDD checks judge test runs);
- a tool that always runs build/test tooling, in a tool allowlist, a ``tool_called`` check, a required step or a
  platform action's ``tool``: ``run_test_suite``, ``run_validation_commands``, ``run_openrewrite_recipe``,
  ``lint_and_format_workspace``. A ``tool_not_called`` check names a tool the run must NOT use: never a build.

A workflow with a ``pipeline.run`` step whose checks are not blocking (e.g.
``team-delivery``): its phases may allowlist ``run_test_suite`` (on a device the agent runs the tests itself), but
nothing at the Stop requires a test run, and the pipeline is the judge of the tests. Such a workflow starts on the
server; there the pipeline is skipped and says so (``pipeline.py``) and each call of a build tool is still refused by
``foreign_build_guard``. A blocking test check (or a blocking ``tool_called`` of a build tool) still refuses it.

Read-only workflows (triage, analysis, incident analysis) declare none of these and keep running on the server. A
sub-workflow is judged at its own start (an incident analysis's bug-fix child is refused there, its parent fails with
the message). A run without a target is the server unless its chat thread runs on a device (``runtime_of``).

Every enforcement point (start, ``change_runtime``, a handover's ``auto`` target, a handoff child) calls
``refuse_server_build``; the refusal is logged with the steps that decided it, and a switch on an existing run also
records the run event ``server_build_refused``. Any other server execution is held by the central guard as backstop.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_NOT_ALLOWED

logger = logging.getLogger(__name__)

EVENT_REFUSED = "server_build_refused"
BUILD_CHECK_TYPES = frozenset({
    "test_command_passed", "tests_red", "tests_green", "confirmed_tests_intact", "reproduces", "lint_passed",
})
BUILD_TOOLS = frozenset({
    "run_test_suite", "run_validation_commands", "run_openrewrite_recipe", "lint_and_format_workspace",
})
_TOOL_KEYS = ("tool", "tools", "allowlist", "tool_name")
_ALLOWLIST_KEY = "allowlist"
PIPELINE_ACTION = "pipeline.run"


def workflow_message(steps: list[str]) -> str:
    named = ", ".join(steps[:4]) + (" …" if len(steps) > 4 else "")
    return (
        f"This workflow builds or tests the repository ({named}), which is not allowed on the Octryx server. "
        "Run it on your Mac (choose your device as the run location) — a sandbox for server runs is coming. "
        "No device yet: pair Claude Code with the launcher (Agents › Install octryx-claude)."
    )


def _walk(value: Any, *, judged_by_pipeline: bool = False) -> Iterator[str]:
    """The build checks and build tools ``value`` declares (``tool_not_called`` entries skipped).

    ``judged_by_pipeline``: the workflow has a ``pipeline.run`` step, so only what the run REQUIRES counts (a
    blocking check); a tool allowlist or an advisory check only permits a test run."""
    if isinstance(value, Mapping):
        kind = str(value.get("type") or "")
        if kind == "tool_not_called":
            return
        if judged_by_pipeline and kind and value.get("blocking") is False:
            return
        if kind in BUILD_CHECK_TYPES:
            yield kind
        for key, item in value.items():
            if key == _ALLOWLIST_KEY and judged_by_pipeline:
                continue
            if key in _TOOL_KEYS:
                names = item if isinstance(item, list) else [item]
                yield from (str(name) for name in names if str(name) in BUILD_TOOLS)
            else:
                yield from _walk(item, judged_by_pipeline=judged_by_pipeline)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, judged_by_pipeline=judged_by_pipeline)


def has_pipeline(definition: Mapping[str, Any] | None) -> bool:
    """Whether a phased ``definition`` has a ``pipeline.run`` step (the platform runs the declared tests)."""
    return any(isinstance(raw, Mapping) and isinstance(raw.get("config"), Mapping)
               and raw["config"].get("action") == PIPELINE_ACTION
               for raw in list((definition or {}).get("nodes") or []))


def _build_step_titles(definition: Mapping[str, Any] | None) -> list[str]:
    steps: list[str] = []
    judged_by_pipeline = has_pipeline(definition)
    for raw in list((definition or {}).get("nodes") or []):
        if not isinstance(raw, Mapping):
            continue
        config = raw.get("config") if isinstance(raw.get("config"), Mapping) else {}
        if next(_walk(config, judged_by_pipeline=judged_by_pipeline), None) is not None:
            title = str(raw.get("label") or raw.get("title") or config.get("title") or raw.get("id") or "a step")
            steps.append(title)
    return steps


def build_steps(definition: Mapping[str, Any] | None = None) -> list[str]:
    """The steps of a phased ``definition`` (its node titles) that build or test."""
    return _build_step_titles(definition)


def builds_or_tests(definition: Mapping[str, Any] | None = None) -> bool:
    """Whether the workflow has a step that builds or tests: only then does a runtime prepare its test environment.

    The workflow's own property, also where the server build lock is lifted (the server pipeline's own tests)."""
    return bool(_build_step_titles(definition))


def runs_on_server(target: Mapping[str, Any] | None, thread: Any = None) -> bool:
    """Whether a run with ``target`` executes on the server: an explicit server target, or none and no device
    thread (``workspace.preparation.runtime_of``'s fallback; a terminal is attached only after the start)."""
    if target is not None:
        return str(target.get("kind") or "") == "server"
    from ..octryx.continuation_marker import _device_target

    return _device_target(thread) is None


def server_build_refusal(target: Mapping[str, Any] | None, *, definition: Mapping[str, Any] | None = None,
                         thread: Any = None) -> tuple[str, list[str]] | None:
    """``(message, steps)`` when this run may not run on the server, else ``None``."""
    if not runs_on_server(target, thread):
        return None
    steps = build_steps(definition)
    return (workflow_message(steps), steps) if steps else None


async def run_definition(db: Any, run: Any) -> dict[str, Any]:
    """The phased definition of an existing run's pinned version (``{}`` when the version is gone)."""
    from ....models import FlowDefinitionVersion

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id or "")
    return dict(version.definition_json or {}) if version is not None else {}


def refuse_server_build(target: Mapping[str, Any] | None, *, workflow_key: str, where: str,
                        definition: Mapping[str, Any] | None = None, thread: Any = None, actor_id: str | None = None,
                        db: Any = None, run: Any = None) -> None:
    """Raise ``WorkflowRunError(server_build_not_allowed)`` (logged) when the run would build on the server.

    ``db``/``run``: an existing run (a switch, a handover) also gets the run event ``server_build_refused`` with the
    reason, and the error is ``persist`` so the route commits that event (the run itself is left unchanged)."""
    from ..records import WorkflowRunError, record_event

    refusal = server_build_refusal(target, definition=definition, thread=thread)
    if refusal is None:
        return
    message, steps = refusal
    logger.warning("server_build_not_allowed: where=%s workflow=%s steps=%s actor=%s", where, workflow_key, steps,
                   actor_id)
    if db is not None and run is not None:
        record_event(db, run, EVENT_REFUSED, node_id=run.current_node_id, actor_id=actor_id,
                     detail={"reason": SERVER_BUILD_NOT_ALLOWED, "where": where, "steps": steps,
                             "target": dict(target) if target is not None else None, "message": message})
    raise WorkflowRunError(SERVER_BUILD_NOT_ALLOWED, message, 409, persist=run is not None)


__all__ = ["BUILD_CHECK_TYPES", "BUILD_TOOLS", "EVENT_REFUSED", "build_steps", "builds_or_tests", "has_pipeline",
           "refuse_server_build", "run_definition", "runs_on_server", "server_build_refusal", "workflow_message"]
