"""The phase's compact run contract in the turn's context, once per contract digest.
It saves a ``workflow_run_status`` round whose large answer may land where the agent cannot read it."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .state import LocalState, read_json, write_private_json

SHOWN_FILE = "phase-brief-shown.json"
HEAD = "Your run contract for this phase (compact; workflow_run_status with detail=true has the rest):\n"
STYLE_HEAD = "\n\nCode style for this run (the platform checks it):\n"
JSON_LATER = "The rest of your run contract is in workflow_run_status (compact by default)."
STYLE_LATER = "\n\nThe code style is in workflow_run_status with detail=true (phase.code_style_brief)."
# Claude Code moves a long hook context into a file the agent cannot read (its protected home): stay well below.
MAX_CHARS = 8000


def _without(value: dict[str, Any], path: list[str]) -> dict[str, Any]:
    head, rest = path[0], path[1:]
    if head not in value:
        return value
    if not rest:
        return {key: item for key, item in value.items() if key != head}
    inner = value[head]
    return {**value, head: _without(inner, rest)} if isinstance(inner, dict) else value


def compact(contract: dict[str, Any]) -> dict[str, Any]:
    view = {key: value for key, value in contract.items() if key != "detail_paths"}
    for name in contract.get("detail_paths") or []:
        view = _without(view, str(name).split("."))
    return view


def _without_brief(view: dict[str, Any]) -> dict[str, Any]:
    phase = view.get("phase")
    return {**view, "phase": {k: v for k, v in phase.items() if k != "brief"}} if isinstance(phase, dict) else view


def _with_rules(phase: dict[str, Any], text: str) -> str:
    # A cut JSON reads as broken, so it is left out whole; the brief always stays.
    brief = str(phase.get("brief") or "").strip()
    if not brief:
        return text
    combined = brief + "\n\n" + text
    return combined if len(combined) <= MAX_CHARS else brief + "\n\n" + JSON_LATER


def phase_brief(state: LocalState, session_key: str, contract: dict[str, Any] | None) -> str:
    phase = contract.get("phase") if isinstance(contract, dict) else None
    if not isinstance(phase, dict) or not contract.get("detail_paths"):
        return ""  # no phase, or a platform without the compact view: the agent reads workflow_run_status
    path = state.session_dir(session_key) / SHOWN_FILE
    shown = read_json(path)
    style = str(phase.get("code_style_brief") or "")
    style_digest = hashlib.sha256(style.encode()).hexdigest() if style else ""
    if shown.get("digest") == contract.get("digest"):
        return ""
    text = _with_rules(phase, HEAD + json.dumps(_without_brief(compact(contract)), ensure_ascii=False,
                                                 separators=(",", ":"), default=str))
    seen = shown.get("style")
    if style_digest and style_digest != seen:
        fits = len(text) + len(STYLE_HEAD) + len(style) <= MAX_CHARS
        text += STYLE_HEAD + style if fits else STYLE_LATER
        seen = style_digest if fits else seen
    write_private_json(path, {"digest": contract.get("digest"), "style": seen})
    return text[:MAX_CHARS]


MAP_SHOWN_FILE = "code-map-shown.json"


def code_map_once(state: LocalState, session_key: str, contract: dict[str, Any] | None, root: str,
                  head: str, style_head: str = "") -> str:
    from .code_map import code_map

    if not isinstance(contract, dict) or not isinstance(contract.get("phase"), dict):
        return ""
    path = state.session_dir(session_key) / MAP_SHOWN_FILE
    app = str(dict(dict(contract.get("preparation") or {}).get("environment") or {}).get("app_folder") or ".")
    if read_json(path).get("app") == app:
        return ""
    text = code_map(root, contract, head, style_head)
    if text:
        write_private_json(path, {"app": app})
    return text


__all__ = ["JSON_LATER", "MAP_SHOWN_FILE", "SHOWN_FILE", "code_map_once", "compact", "phase_brief"]
