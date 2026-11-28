"""A run that builds or tests the repository never runs on the server."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

from app.services.execution_runtime.build_guard_rules import SERVER_BUILD_NOT_ALLOWED

logger = logging.getLogger(__name__)

EVENT_REFUSED = "server_build_refused"
BUILD_CHECK_TYPES = frozenset({
    "test_command_passed", "tests_red", "tests_green", "confirmed_tests_intact", "reproduces",
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
    return _build_step_titles(definition)


def builds_or_tests(definition: Mapping[str, Any] | None = None) -> bool:
    return bool(_build_step_titles(definition))


def runs_on_server(target: Mapping[str, Any] | None, thread: Any = None) -> bool:
    if target is not None:
        return str(target.get("kind") or "") == "server"
    from ..octryx.continuation_marker import _device_target

    return _device_target(thread) is None


def server_build_refusal(target: Mapping[str, Any] | None, *, definition: Mapping[str, Any] | None = None,
                         thread: Any = None) -> tuple[str, list[str]] | None:
    if not runs_on_server(target, thread):
        return None
    steps = build_steps(definition)
    return (workflow_message(steps), steps) if steps else None


async def run_definition(db: Any, run: Any) -> dict[str, Any]:
    from ....models import FlowDefinitionVersion

    version = await db.get(FlowDefinitionVersion, run.flow_definition_version_id or "")
    return dict(version.definition_json or {}) if version is not None else {}


def refuse_server_build(target: Mapping[str, Any] | None, *, workflow_key: str, where: str,
                        definition: Mapping[str, Any] | None = None, thread: Any = None, actor_id: str | None = None,
                        db: Any = None, run: Any = None) -> None:
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
