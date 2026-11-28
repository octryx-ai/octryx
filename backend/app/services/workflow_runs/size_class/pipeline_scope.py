"""Whether the pipeline of a size class runs the system test (data: ``pipeline_scope``)."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from . import CONTEXT_KEY, class_config

KEY = "pipeline_scope"
SYSTEM_ALWAYS, SYSTEM_LABELS = "always", "labels"
MODES = frozenset({SYSTEM_ALWAYS, SYSTEM_LABELS})


def runs_system_test(run: WorkflowRun) -> bool:
    settings = class_config(run).get(KEY)
    if not isinstance(settings, dict) or settings.get("system_test", SYSTEM_ALWAYS) != SYSTEM_LABELS:
        return True
    labels = {str(label).strip().lower() for label in dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get(
        "labels") or []}
    return bool(labels & {str(label).strip().lower() for label in settings.get("system_test_labels") or []})


def agent_runs_system_test(run: WorkflowRun) -> bool:
    settings = class_config(run).get(KEY)
    return not (isinstance(settings, dict) and settings.get("agent_system_test") == "pipeline")


def errors(name: str, settings: Any) -> list[str]:
    if isinstance(settings, dict) and settings.get("agent_system_test", "phase") not in ("phase", "pipeline"):
        return [f"class {name}: pipeline_scope agent_system_test is \"phase\" or \"pipeline\"."]
    if not isinstance(settings, dict) or settings.get("system_test", SYSTEM_ALWAYS) not in MODES:
        return [f"class {name}: pipeline_scope is {{\"system_test\": \"always\" | \"labels\", "
                f"\"system_test_labels\": [...]}}."]
    wanted = settings.get("system_test_labels")
    if settings.get("system_test") == SYSTEM_LABELS and not (isinstance(wanted, list) and wanted and all(
            isinstance(label, str) and label.strip() for label in wanted)):
        return [f"class {name}: pipeline_scope system_test labels names the labels that keep the system test."]
    return []


__all__ = ["KEY", "agent_runs_system_test", "errors", "runs_system_test"]
