"""The engine's per-node buckets in the run context (results, evidence, answers) and its wait marker."""

from __future__ import annotations

from typing import Any

from ...models import WorkflowRun

_WAIT = object()


def _context(run: WorkflowRun) -> dict[str, Any]:
    return dict(run.context or {})


def _set_context(run: WorkflowRun, key: str, node_id: str, value: Any) -> None:
    context = _context(run)
    bucket = dict(context.get(key) or {})
    bucket[node_id] = value
    context[key] = bucket
    run.context = context
