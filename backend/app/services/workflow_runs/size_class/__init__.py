"""A run's size class from its workflow's ``size_classes`` block (``context.size_class``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event
from .rules import facts_of, first_match

CONTEXT_KEY = "size_class"
EVENT_CLASSIFIED = "size_classified"
EVENT_ESCALATED = "size_escalated"


def _entry(run: WorkflowRun | None) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(CONTEXT_KEY) or {}) if run is not None else {}


def size_of(run: WorkflowRun | None) -> str:
    """The run's class name; ``""`` without one (the workflow's full behaviour)."""
    return str(_entry(run).get("class") or "")


def class_config(run: WorkflowRun | None) -> dict[str, Any]:
    """The settings of the run's current class (``{}`` without a class)."""
    entry = _entry(run)
    return dict(dict(entry.get("classes") or {}).get(str(entry.get("class") or "")) or {})


def skipped_nodes(settings: dict[str, Any], labels: set[str]) -> list[str]:
    """The class's skipped steps for an item with ``labels`` (a step's ``unless_labels`` keeps it)."""
    return [str(skip["node"]) for skip in list(settings.get("skip_nodes") or [])
            if not labels & {str(label).strip().lower() for label in skip.get("unless_labels") or []}]


async def _continues_unclassified(db: AsyncSession, run: WorkflowRun) -> str:
    from ..epic_chain import CHAIN_KEY

    for source in (str(dict(dict(run.context or {}).get(CHAIN_KEY) or {}).get("after_run") or ""),
                   str(run.parent_run_id or "")):
        earlier = await db.get(WorkflowRun, source) if source else None
        if earlier is not None and CONTEXT_KEY not in dict(earlier.context or {}):
            return source
    return ""


def _store(db: AsyncSession, run: WorkflowRun, entry: dict[str, Any], kind: str, detail: dict[str, Any]) -> None:
    run.context = {**dict(run.context or {}), CONTEXT_KEY: entry}
    record_event(db, run, kind, node_id=run.current_node_id, detail=detail)


async def classify_at_start(db: AsyncSession, run: WorkflowRun, definition: dict[str, Any] | None,
                            item: Any) -> str:
    """The run's class from the definition's block; ``""`` when the run takes none."""
    block = dict(definition or {}).get("size_classes")
    if not isinstance(block, dict):
        return ""
    if earlier := await _continues_unclassified(db, run):
        record_event(db, run, EVENT_CLASSIFIED, node_id=run.current_node_id,
                     detail={"class": None, "matched": f"continues run {earlier}, started without a class"})
        return ""
    name, rule, matched = first_match(block, item)
    classes = dict(block.get("classes") or {})
    labels = facts_of(item)["labels"]
    skips = skipped_nodes(dict(classes.get(name) or {}), labels)
    _store(db, run, {"class": name, "initial": name, "rule": rule, "matched": matched, "labels": sorted(labels),
                     "skips": skips, "classes": classes},
           EVENT_CLASSIFIED, {"class": name, "rule": rule, "matched": matched, "skips": skips})
    return name


def escalate(db: AsyncSession, run: WorkflowRun, *, cause: str) -> str:
    """Raise the run to its class's ``escalate_to`` because the lighter path did not get through; ``""`` when the
    class names none (then the workflow's own limits apply)."""
    entry = _entry(run)
    after = str(class_config(run).get("escalate_to") or "")
    if not after:
        return ""
    skips = skipped_nodes(dict(dict(entry.get("classes") or {}).get(after) or {}), set(entry.get("labels") or []))
    history = [*list(entry.get("escalations") or []), {"from": entry.get("class"), "to": after, "cause": cause}]
    _store(db, run, {**entry, "class": after, "skips": skips, "escalations": history},
           EVENT_ESCALATED, {"from": entry.get("class"), "to": after, "cause": cause, "skips": skips})
    return after


__all__ = ["CONTEXT_KEY", "EVENT_CLASSIFIED", "EVENT_ESCALATED", "class_config", "classify_at_start", "escalate",
           "size_of", "skipped_nodes"]
