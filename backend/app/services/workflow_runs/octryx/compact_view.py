"""The compact run contract the agent reads: what the phase asks of it, without the detail it rarely needs."""

from __future__ import annotations

from typing import Any

# What only the launcher or a curious agent needs, as dotted paths into the contract; each is in ``detail=true``.
DETAIL_PATHS = (
    "preparation", "facts", "digest", "version", "link", "prompt_texts", "work_git",
    "phase.code_style", "phase.code_style_brief", "phase.previous_change",
    "phase.environment_file", "phase.agent", "phase.knowledge_first", "phase.web_requests",
    "phase.tools.deny", "phase.tools.on_device_note",  # allow stays: it names the phase's own platform tools
)
PATHS_KEY = "detail_paths"
DETAIL_NOTE = "workflow_run_status with detail=true adds: "


def _without(value: dict[str, Any], path: list[str], omitted: list[str], name: str) -> dict[str, Any]:
    head, rest = path[0], path[1:]
    if head not in value or (not rest and value[head] in (None, "", [], {})):
        return value
    if not rest:
        omitted.append(name)
        return {key: item for key, item in value.items() if key != head}
    inner = value[head]
    return {**value, head: _without(inner, rest, omitted, name)} if isinstance(inner, dict) else value


def compact(contract: dict[str, Any], paths: tuple[str, ...] | list[str] = DETAIL_PATHS) -> dict[str, Any]:
    view: dict[str, Any] = {key: value for key, value in contract.items() if key != PATHS_KEY}
    omitted: list[str] = []
    for name in paths:
        view = _without(view, name.split("."), omitted, name)
    return {**view, "detail_omitted": DETAIL_NOTE + ", ".join(omitted)} if omitted else view


__all__ = ["DETAIL_PATHS", "PATHS_KEY", "compact"]
