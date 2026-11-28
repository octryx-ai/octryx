"""A pipeline command the environment could not run pauses the run ``environment_not_ready`` (no fix round)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Project, WorkflowRun
from ..workflow_checks.test_command_outcome import MAX_EXCERPT

SOURCE = "pipeline"


def _changed_names(run: WorkflowRun) -> set[str] | None:
    from .octryx.system_tests import changed_files

    files = changed_files(dict(run.context or {}).get("device_change"))
    if files is None:
        return None
    names: set[str] = set()
    for name in files:
        parts = name.split("/")
        names.update(parts)
        names.update(part.rsplit(".", 1)[0] for part in parts)
    return names


def _tests_or_collection(text: str, stacks: dict[str, Any]) -> bool:
    from ..engineering_knowledge.stacks import collection_errors
    from ..workflow_checks.test_command_outcome import _COLLECTION, _SUMMARIES

    return any(pattern.search(text) for pattern in (_COLLECTION, *_SUMMARIES, *collection_errors(stacks)))


def failure_of(item: dict[str, Any], stacks: dict[str, Any], changed: set[str] | None) -> dict[str, Any] | None:
    from ..engineering_knowledge.stacks import environment_errors

    text = str(item.get("output_tail") or "")
    if item.get("failed_tests") or _tests_or_collection(text, stacks):
        return None
    codes, patterns = environment_errors(stacks)
    code = item.get("exit_code")
    found = next((match for pattern in patterns if (match := pattern.search(text))), None)
    if found is None and code not in codes:
        return None
    module = (found.groupdict().get("module") or "") if found is not None else ""
    if module and changed is not None and module.split(".")[0] in changed:
        return None  # the change touches a file or folder of that name: an import the agent broke
    line = found.group(0).strip()[:300] if found is not None else f"exit {code}"
    return {"kind": "environment", "source": SOURCE, "command": str(item.get("command") or ""), "exit_code": code,
            "reason": f"the pipeline could not run `{item.get('command')}`: {line}",
            "excerpt": text[-MAX_EXCERPT:]}


async def environment_failure(db: AsyncSession, run: WorkflowRun,
                              red: list[dict[str, Any]]) -> dict[str, Any] | None:
    from ..engineering_knowledge.stacks import for_project

    if not red:
        return None
    project = await db.get(Project, run.project_id) if getattr(run, "project_id", None) else None
    stacks = await for_project(db, project)
    changed = _changed_names(run)
    return next((failure for item in red if (failure := failure_of(item, stacks, changed))), None)


__all__ = ["SOURCE", "environment_failure", "failure_of"]
