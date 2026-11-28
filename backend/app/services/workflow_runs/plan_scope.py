"""Expensive path classes (``device_runs.expensive_paths``) and the recorded change plan's scope: a write outside
it pauses the run as ``needs_approval``; a plan naming no expensive class counts as approved."""

from __future__ import annotations

import re
from typing import Any

from .protected_paths import path_matches

KIND = "change_plan"
SETTING = "expensive_paths"
CONTEXT_KEY = "plan_scope"
DEFAULT_EXPENSIVE_PATHS: dict[str, list[str]] = {
    "migrations": ["**/migrations/**", "**/alembic/**", "**/*.sql"],
    "auth": ["**/auth/**", "**/permissions/**", "**/*rbac*"],
    # Only the contract files: routes and handlers are everyday backend work.
    "public_api": ["**/openapi*.json", "**/openapi*.yaml", "**/openapi*.yml", "**/*.proto", "**/schema.graphql"],
    "infra": ["Dockerfile*", "**/Dockerfile*", "**/deploy/**", "**/k8s/**", "**/helm/**", "**/terraform/**",
              ".github/workflows/**"],
}
LIST_FIELDS = ("parts", "paths", "endpoints", "expensive", "risks", "open_questions")
MAX_ITEMS, MAX_CHARS = 100, 500
_GLOB = re.compile(r"^[^\s/][^\s]*$")
PLANNED, UNPLANNED, OUTSIDE = "plan", "expensive_path", "outside_plan"


def expensive_classes(section: dict[str, Any] | None) -> dict[str, list[str]]:
    stored = dict(section or {}).get(SETTING)
    if not isinstance(stored, dict):
        return {key: list(value) for key, value in DEFAULT_EXPENSIVE_PATHS.items()}
    return {str(key): [str(item) for item in value] for key, value in stored.items() if isinstance(value, list)}


def classes_of(path: str, classes: dict[str, list[str]]) -> list[str]:
    return [name for name, globs in classes.items() if any(path_matches(path, glob) for glob in globs)]


def _texts(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return [str(item).strip()[:MAX_CHARS] for item in items if str(item or "").strip()][:MAX_ITEMS]


def validate_change_plan(raw: dict[str, Any], classes: dict[str, list[str]] | None = None) -> tuple[dict, list[str]]:
    record = {field: _texts(raw.get(field)) for field in LIST_FIELDS}
    known = classes if classes is not None else expensive_classes(None)
    problems = [] if record["parts"] else ["parts: at least one part of the change"]
    problems += [] if record["paths"] else ["paths: the files or globs the build will change"]
    problems += [f"paths: '{glob}' is not a relative path or glob" for glob in record["paths"]
                 if not _GLOB.match(glob) or ".." in glob.split("/")]
    # A Workspace may name its own classes; only a check against its classes can refuse an unknown one.
    problems += [f"expensive: '{name}' is not one of {', '.join(known)}" for name in record["expensive"]
                 if classes is not None and name not in known]
    touched = sorted({name for glob in record["paths"] for name in classes_of(glob, known)})
    problems += [f"expensive: the paths touch '{name}', so the plan must name it" for name in touched
                 if name not in record["expensive"]]
    return record, problems


def scope_state(run: Any) -> dict[str, Any]:
    from .phase_outputs import recorded_output

    plan = dict((recorded_output(run, KIND) or {}).get("record") or {})
    stored = dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    approved = bool(plan) and (not plan.get("expensive") or stored.get("approved_hash") == plan_hash(plan))
    return {"plan": plan, "approved": approved, "paths": list(plan.get("paths") or []),
            "granted": list(stored.get("paths") or [])}


def plan_hash(plan: dict[str, Any]) -> str:
    from .phase_outputs import output_hash

    return output_hash(plan)


def refusal(names: list[str], state: dict[str, Any], classes: dict[str, list[str]]) -> tuple[str, str, list[str]]:
    for name in names:
        if any(path_matches(name, glob) for glob in state.get("granted") or []):
            continue
        touched = classes_of(name, classes)
        if state.get("approved"):
            if not any(path_matches(name, glob) for glob in state.get("paths") or []):
                return OUTSIDE, name, touched
        elif touched:
            return (PLANNED if state.get("plan") else UNPLANNED), name, touched
    return "", "", []


def approve(run: Any, detail: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    state, stored = scope_state(run), dict(dict(run.context or {}).get(CONTEXT_KEY) or {})
    if detail.get("kind") == PLANNED and state["plan"]:
        stored["approved_hash"] = plan_hash(state["plan"])
    if detail.get("path") and detail.get("kind") != PLANNED:
        stored["paths"] = [*stored.get("paths", []), str(detail["path"])]
    stored["approved"] = [*stored.get("approved", []), {"kind": detail.get("kind"), "path": detail.get("path"),
                                                         "by": user_id}][-50:]
    run.context = {**dict(run.context or {}), CONTEXT_KEY: stored}
    return stored
