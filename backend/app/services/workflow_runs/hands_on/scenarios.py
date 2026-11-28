"""The hands-on scenarios: what a person would do with the built app, as fixed steps the device runs in a browser (an
app can pass every pipeline and review and still lose all data on reload)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

OPS = ("goto", "click", "fill", "press", "reload", "restart", "expect_text", "expect_no_text", "wait", "screenshot")
PARTS = ("feature", "regression")
#: The regression checks a scenario can cover; which ones a run requires is its hands-on node's
#: ``regression_covers`` (the workflow definition).
COVERS = ("app_loads", "persistence_reload", "empty_state", "mobile_390", "desktop_1280", "invalid_input")
COVERS_KEY = "regression_covers"
VIEWPORT_OF = {"mobile_390": 390, "desktop_1280": 1280}
MAX_SCENARIOS = 20
MAX_STEPS = 40
MAX_TEXT = 300
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}


class ScenarioError(ValueError):
    pass


def _text(value: Any, where: str, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str | int | float) or not str(value).strip() or len(str(value)) > MAX_TEXT:
        raise ScenarioError(f"{where}: a text of at most {MAX_TEXT} characters is required")
    return str(value).strip()


def _step(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("do") not in OPS:
        raise ScenarioError(f"{where}: a step needs \"do\" in {', '.join(OPS)}")
    op = raw["do"]
    step: dict[str, Any] = {"do": op}
    if op == "goto":
        path = _text(raw.get("path", "/"), f"{where}.path")
        if not path.startswith("/") or "//" in path or re.search(r"\s", path):
            raise ScenarioError(f"{where}.path: a path of the app, starting with /")
        step["path"] = path
    elif op in ("click", "expect_text", "expect_no_text"):
        step["text"] = _text(raw.get("text"), f"{where}.text")
    elif op == "fill":
        step["label"] = _text(raw.get("label"), f"{where}.label")
        step["value"] = str(raw.get("value") if raw.get("value") is not None else "")[:MAX_TEXT]
    elif op == "press":
        step["key"] = _text(raw.get("key"), f"{where}.key")
    elif op == "wait":
        ms = raw.get("ms")
        if type(ms) is not int or not 0 < ms <= 5000:
            raise ScenarioError(f"{where}.ms: 1 to 5000")
        step["ms"] = ms
    elif op == "screenshot":
        step["name"] = re.sub(r"[^a-z0-9_-]+", "-", _text(raw.get("name"), f"{where}.name").lower())[:60]
    return step


def _steps(raw: Any, where: str, *, required: bool) -> list[dict[str, Any]]:
    if raw is None and not required:
        return []
    if not isinstance(raw, list) or (required and not raw) or len(raw) > MAX_STEPS:
        raise ScenarioError(f"{where}: 1 to {MAX_STEPS} steps")
    return [_step(item, f"{where}[{index}]") for index, item in enumerate(raw)]


def scenario(raw: Any, index: int) -> dict[str, Any]:
    where = f"scenarios[{index}]"
    if not isinstance(raw, dict):
        raise ScenarioError(f"{where}: an object")
    part = raw.get("part")
    if part not in PARTS:
        raise ScenarioError(f"{where}.part: feature or regression")
    fresh = raw.get("fresh_profile", True)
    if type(fresh) is not bool:
        raise ScenarioError(f"{where}.fresh_profile: true or false")
    viewport = raw.get("viewport") or DEFAULT_VIEWPORT
    if not isinstance(viewport, dict) or any(type(viewport.get(key)) is not int or not 240 <= viewport[key] <= 4000
                                             for key in ("width", "height")):
        raise ScenarioError(f"{where}.viewport: width and height in pixels")
    covers = raw.get("covers") or []
    if not isinstance(covers, list) or any(not isinstance(item, str) for item in covers):
        raise ScenarioError(f"{where}.covers: a list of names")
    covers = [item for item in covers if item in COVERS]
    for name, width in VIEWPORT_OF.items():
        if name in covers and viewport["width"] != width:
            raise ScenarioError(f"{where}: {name} needs the viewport width {width}")
    steps = _steps(raw.get("steps"), f"{where}.steps", required=True)
    if "persistence_reload" in covers and not any(step["do"] in ("reload", "restart") for step in steps):
        raise ScenarioError(f"{where}: persistence_reload needs a reload or restart step")
    seed = _steps(raw.get("seed"), f"{where}.seed", required=not fresh)
    return {"id": f"S{index + 1}", "part": part, "title": _text(raw.get("title"), f"{where}.title"),
            "fresh_profile": fresh, "seed": seed, "viewport": {"width": viewport["width"],
                                                               "height": viewport["height"]},
            "covers": covers, "steps": steps}


def validate(answer: Any, *, required: Sequence[str] = (), keeps_data: bool = True) -> list[dict[str, Any]]:
    raw = answer.get("scenarios") if isinstance(answer, dict) else None
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SCENARIOS:
        raise ScenarioError(f"scenarios: 1 to {MAX_SCENARIOS} scenarios")
    scenarios = [scenario(item, index) for index, item in enumerate(raw)]
    if not any(item["part"] == "feature" for item in scenarios):
        raise ScenarioError("at least one feature scenario (the work item's acceptance criteria)")
    covered = {name for item in scenarios if item["part"] == "regression" for name in item["covers"]}
    missing = [name for name in required if name not in covered and (keeps_data or name != "persistence_reload")]
    if not keeps_data and (seeded := [item["id"] for item in scenarios if item.get("seed")]):
        raise ScenarioError("this app keeps no data across a restart: create the data in the scenario's own steps "
                            "(fresh_profile true, no seed) in " + ", ".join(seeded))
    if missing:
        raise ScenarioError("the regression scenarios do not cover: " + ", ".join(missing))
    return scenarios


def covers_errors(graph: Any) -> list[dict[str, str]]:
    # A misspelt name would silently require nothing.
    from ..graph_node_rules import _error, _name

    errors = []
    for node in graph.nodes.values():
        value = dict(node.config or {}).get(COVERS_KEY)
        if value is None:
            continue
        if not isinstance(value, list) or any(item not in COVERS for item in value):
            errors.append(_error(COVERS_KEY, f"{_name(node)}: {COVERS_KEY} is a list of: {', '.join(COVERS)}.",
                                 node_id=node.id))
    return errors


def render_step(step: dict[str, Any]) -> str:
    detail = " ".join(f"{key}={value!r}" for key, value in step.items() if key != "do")
    return f"{step['do']} {detail}".strip()


__all__ = ["COVERS", "COVERS_KEY", "DEFAULT_VIEWPORT", "OPS", "PARTS", "ScenarioError", "covers_errors", "render_step",
           "scenario", "validate"]
