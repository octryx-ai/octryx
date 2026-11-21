"""The device reuses a build it already made for the same inputs; the run's history names each hit and miss
(never rebuild everything every time).

The stacks name their build artifacts as data (stacks.json ``build_artifacts``); the pipeline's and the hands-on
test's views carry them to the launcher (``clients/octryx-claude/octryx_claude/build_cache.py``), which reports every
hit and miss with its key. Only an exact key is reused there; a stack without the entry builds.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .records import record_event

EVENT = "build_cache"
RESULTS = frozenset({"hit", "miss"})


def view() -> dict[str, Any]:
    """``{"build_artifacts": [...]}`` for a device view, ``{}`` when no stack declares one."""
    from ..engineering_knowledge.stacks import build_artifacts

    found = build_artifacts()
    return {"build_artifacts": found} if found else {}


def record(db: AsyncSession, run: WorkflowRun, report: dict[str, Any]) -> None:
    """An event per reported hit or miss (result, key, command, seconds), anything else dropped."""
    notes = report.get("build_cache")
    for note in notes[:20] if isinstance(notes, list) else []:
        if not isinstance(note, dict) or note.get("result") not in RESULTS:
            continue
        detail = {key: note[key] for key in ("result", "key", "command", "seconds", "exit_code")
                  if isinstance(note.get(key), str | int | float) and not isinstance(note.get(key), bool)}
        detail["key"] = str(detail.get("key") or "")[:64]
        detail["command"] = str(detail.get("command") or "")[:200]
        record_event(db, run, EVENT, node_id=run.current_node_id, detail=detail)


__all__ = ["EVENT", "record", "view"]
