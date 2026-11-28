"""The hands-on scenarios a repository keeps itself (``tests/hands_on/**/*.json`` in the app folder)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FOLDER = "tests/hands_on"
BUGS = "tests/hands_on/bugs"
OPS = {"goto", "click", "fill", "press", "reload", "restart", "expect_text", "expect_no_text", "wait", "screenshot"}
# The keys each step needs (hands_on_browser.Session.step). Each step is checked here with a message that names the
# step and its keys (a bare KeyError in the browser tells the agent nothing); the two obvious spellings
# ({"do": "goto", "url": "/"}, {"do": "click", "label": ...}) are taken as meant.
REQUIRED = {"goto": ("path",), "click": ("text",), "fill": ("label", "value"), "press": ("key",), "wait": ("ms",),
            "expect_text": ("text",), "expect_no_text": ("text",), "screenshot": ("name",), "reload": (),
            "restart": ()}
MAX_FILES = 200
MAX_STEPS = 40


def _scenario(raw: Any, ident: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list) or not raw["steps"] \
            or len(raw["steps"]) > MAX_STEPS:
        raise ValueError("a scenario needs 1 to 40 steps")
    steps = [step for step in raw["steps"] + list(raw.get("seed") or []) if isinstance(step, dict)]
    if len(steps) != len(raw["steps"]) + len(raw.get("seed") or []) or any(step.get("do") not in OPS
                                                                         for step in steps):
        raise ValueError(f"every step needs \"do\" in {', '.join(sorted(OPS))}")
    for index, step in enumerate(steps, 1):
        _normalize(step)
        missing = [key for key in REQUIRED[step["do"]] if step.get(key) in (None, "")]
        if missing:
            raise ValueError(f"step {index} ({step['do']}) needs {', '.join(REQUIRED[step['do']])}; missing "
                             f"{', '.join(missing)} (steps: " + "; ".join(
                                 f"{op}: {', '.join(keys) or '-'}" for op, keys in REQUIRED.items()) + ")")
    viewport = raw.get("viewport") if isinstance(raw.get("viewport"), dict) else {"width": 1280, "height": 800}
    fresh = raw.get("fresh_profile", True) is not False
    return {"id": ident, "part": "regression", "title": str(raw.get("title") or ident)[:200], "fresh_profile": fresh,
            "seed": list(raw.get("seed") or []) if not fresh else [], "steps": list(raw["steps"]),
            "viewport": {"width": int(viewport.get("width") or 1280), "height": int(viewport.get("height") or 800)},
            "covers": []}


def _normalize(step: dict[str, Any]) -> None:
    if step["do"] == "goto" and "path" not in step and str(step.get("url") or "").startswith("/"):
        step["path"] = step.pop("url")
    if step["do"] == "click" and "text" not in step and step.get("label"):
        step["text"] = step.pop("label")


def load(app: Path, *, bug_key: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    folder = app / (BUGS if bug_key else FOLDER)
    pattern = f"{bug_key}*.json" if bug_key else "**/*.json"
    scenarios: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    for path in sorted(folder.glob(pattern))[:MAX_FILES] if folder.is_dir() else []:
        relative = path.relative_to(app).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["scenarios"] if isinstance(data, dict) and "scenarios" in data else [data]
            if not isinstance(items, list) or not items:
                raise ValueError("no scenario")
            scenarios += [_scenario(item, f"repo:{relative}#{index}") for index, item in enumerate(items, 1)]
        except (OSError, ValueError, KeyError, TypeError) as error:
            broken.append({"id": f"repo:{relative}", "passed": False, "title": relative,
                           "code": "scenario_file_invalid",
                           "error": f"not a hands-on scenario file: {str(error)[:200]}", "screenshots": []})
    return scenarios, broken


__all__ = ["BUGS", "FOLDER", "load"]
