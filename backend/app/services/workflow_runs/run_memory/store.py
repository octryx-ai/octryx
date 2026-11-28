"""Where the run memory lives (the repository record, per app) and what a phase gets of it at its entry."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ....models import WorkflowRun
from ....time_utils import utc_now

RECORD_KEY = "run_memory"
CONTEXT_KEY = "run_memory"
EVENT_USED = "run_memory_used"
EVENT_LEARNED = "run_memory_learned"
SETTING = "run_memory"


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("run_memory.json").read_text(encoding="utf-8"))


def bounded(text: Any) -> str:
    return " ".join(str(text or "").split())[: int(data()["max_text"])]


def app_of(run: WorkflowRun) -> str:
    from ..workspace.run_app import run_environment_file
    from ..workspace.spec import app_folder

    file = run_environment_file(run)
    return app_folder(file) if file else "."


async def record_of(db: Any, run: WorkflowRun) -> Any:
    from ..platform.repo_ref import _record, parse_repository

    ref = parse_repository(run.repository)
    return await _record(db, run, ref) if ref is not None else None


def memory_of(record: Any, app: str) -> dict[str, list[dict[str, Any]]]:
    stored = dict(dict(record.config_json or {}).get(RECORD_KEY) or {}) if record is not None else {}
    found = stored.get(app)
    return {kind: list(entries) for kind, entries in dict(found).items() if isinstance(entries, list)} if isinstance(
        found, dict) else {}


async def remember(db: Any, run: WorkflowRun, kind: str, key: str, entry: dict[str, Any]) -> bool:
    from ...observability.workflow_metrics import memory_learned

    record = await record_of(db, run)
    if record is None or kind not in data()["kinds"]:
        return False
    app = app_of(run)
    memory = memory_of(record, app)
    entries = [item for item in memory.get(kind, []) if item.get("key") != key]
    known = len(entries) != len(memory.get(kind, []))
    entries.insert(0, {**entry, "key": key, "run_id": run.id, "at": utc_now().isoformat()})
    memory[kind] = entries[: int(data()["kinds"][kind]["max"])]
    stored = dict(dict(record.config_json or {}).get(RECORD_KEY) or {})
    record.config_json = {**dict(record.config_json or {}), RECORD_KEY: {**stored, app: memory}}
    if not known:
        memory_learned(kind)
    return not known


async def _enabled(db: Any, run: WorkflowRun) -> bool:
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import device_runs_section

    if not getattr(run, "project_id", None):
        return True
    loaded = await load_workspace_policy(db, run.project_id)
    return (device_runs_section(loaded.policy.raw) if loaded.policy is not None else {}).get(SETTING) is not False


async def entered(db: Any, run: WorkflowRun, node: Any) -> None:
    """A phase's entry (the run is claimed): the app's memory for this pass, kept in the run's context for the
    brief, and one ``run_memory_used`` event with what it holds (the metric and the e2e report read it)."""
    from ..records import record_event

    if not await _enabled(db, run):
        return
    record = await record_of(db, run)
    memory = memory_of(record, app_of(run))
    counts = {kind: len(entries) for kind, entries in memory.items() if entries}
    entry = dict(run.node_state or {}).get("entry")
    run.context = {**dict(run.context or {}), CONTEXT_KEY: {"node_id": node.id, "entry": entry, "app": app_of(run),
                                                            "entries": memory}}
    if counts:
        record_event(db, run, EVENT_USED, node_id=node.id, detail={"app": app_of(run), "counts": counts,
                                                                    "entry": entry})


def for_brief(run: Any) -> dict[str, list[dict[str, Any]]]:
    """The memory the current pass holds (``{}`` when none was given)."""
    found = dict(dict(getattr(run, "context", None) or {}).get(CONTEXT_KEY) or {})
    current = (getattr(run, "current_node_id", None), dict(getattr(run, "node_state", None) or {}).get("entry"))
    return dict(found.get("entries") or {}) if (found.get("node_id"), found.get("entry")) == current else {}


__all__ = ["CONTEXT_KEY", "EVENT_LEARNED", "EVENT_USED", "RECORD_KEY", "app_of", "bounded", "data", "entered",
           "for_brief", "memory_of", "record_of", "remember"]
