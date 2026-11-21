"""Whether the pipeline of a size class runs the system test (data: ``pipeline_scope``).

Measured on a small Flutter bug: the pipeline took 191-212 s, of which ``flutter test``
14-26 s and the system test (a web build plus a navigation smoke test) 177-186 s, while the agent's own work was
93 s. A class names ``"pipeline_scope": {"system_test": "always" | "labels", "system_test_labels": [...]}``: with
``labels`` the system test runs only for an item carrying one of the labels (the same rule as the class's hands-on
skip); the unit test command always runs, and so does the base-commit proof. Without the key
the pipeline runs everything (classes M and L, and the nightly).
"""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from . import CONTEXT_KEY, class_config

KEY = "pipeline_scope"
SYSTEM_ALWAYS, SYSTEM_LABELS = "always", "labels"
MODES = frozenset({SYSTEM_ALWAYS, SYSTEM_LABELS})


def runs_system_test(run: WorkflowRun) -> bool:
    """Whether this run's pipeline runs the declared system test."""
    settings = class_config(run).get(KEY)
    if not isinstance(settings, dict) or settings.get("system_test", SYSTEM_ALWAYS) != SYSTEM_LABELS:
        return True
    labels = {str(label).strip().lower() for label in dict(dict(run.context or {}).get(CONTEXT_KEY) or {}).get(
        "labels") or []}
    return bool(labels & {str(label).strip().lower() for label in settings.get("system_test_labels") or []})


def agent_runs_system_test(run: WorkflowRun) -> bool:
    """Whether the phase's agent must run the system test itself before the pipeline (``agent_system_test``; default
    yes). Example: an agent ran the system test four times (~4.5 min) right before
    the pipeline that always runs it; with ``"agent_system_test": "pipeline"`` the Stop's suite check leaves it to
    the pipeline (the system test still runs on every pass)."""
    settings = class_config(run).get(KEY)
    return not (isinstance(settings, dict) and settings.get("agent_system_test") == "pipeline")


def errors(name: str, settings: Any) -> list[str]:
    """The block's problems, as sentences (the schema wraps them)."""
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
