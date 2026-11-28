"""The device reuses a build it already made for the same inputs; the run's history names each hit and miss (never
rebuild everything every time)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .records import record_event

EVENT = "build_cache"
RESULTS = frozenset({"hit", "miss"})


def view() -> dict[str, Any]:
    from ..engineering_knowledge.stacks import build_artifacts

    found = build_artifacts()
    return {"build_artifacts": found} if found else {}


def record(db: AsyncSession, run: WorkflowRun, report: dict[str, Any]) -> None:
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
