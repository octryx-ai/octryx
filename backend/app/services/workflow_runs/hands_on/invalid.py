"""A platform-written feature scenario that tests nothing never sends a fix back.

Example: scenarios S1 and S2 seeded grinder M1, restarted the browser and clicked "M1". The app keeps its
data in memory only, so M1 was gone; both failed at "click M1", before the grind setting they check, on the fix and
on the base alike, and sent the run back to the fix three times (24 min of agent work for nothing). The launcher runs
a red feature scenario once more on the base (``hands_on_base``); one that fails there at the same step, before the
step it checks, is ``invalid``: reported, counted, never red. When its seed's data was gone after the restart, the
run memory keeps that the app holds no data across a restart, so the next scenarios seed in the same session.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from ..records import record_event

EVENT = "hands_on_scenario_invalid"
DATA_LOST = "data_lost_after_restart"
REASONS = {DATA_LOST: "the data its seed created is gone after the restart (the app keeps no data across one)",
           "setup_fails_on_base": "its setup fails on the base commit too, before the step it checks"}
FACT_KIND, FACT_KEY = "app_fact", "data_not_persistent"


def invalid_result(result: dict[str, Any], reported: dict[str, Any]) -> dict[str, Any]:
    """``result`` not counted when the device marked the scenario invalid on the base."""
    found = reported.get("invalid")
    if result["passed"] or result.get("part") != "feature" or not isinstance(found, dict):
        return result
    reason = str(found.get("reason") or "")
    return {**result, "passed": True, "invalid": reason if reason in REASONS else "setup_fails_on_base",
            "invalid_text": f"tests nothing: {REASONS.get(reason, REASONS['setup_fails_on_base'])}"
                            + (f" ({str(found.get('error'))[:200]})" if found.get("error") else "")}


async def record(db: AsyncSession, run: WorkflowRun, results: list[dict[str, Any]]) -> None:
    """An event and a count per invalid scenario; the app fact for the run memory when data did not survive."""
    from ...observability.hands_on_metrics import count_invalid
    from ..run_memory.store import remember

    for item in results:
        if not item.get("invalid"):
            continue
        record_event(db, run, EVENT, node_id=run.current_node_id, detail={
            "scenario": item["id"], "title": item.get("title"), "reason": item["invalid"],
            "text": item.get("invalid_text"), "failed_step": item.get("failed_step")})
        count_invalid(str(item["invalid"]))
        if item["invalid"] == DATA_LOST:
            await remember(db, run, FACT_KIND, FACT_KEY, {"fact": REASONS[DATA_LOST], "scenario": item["id"]})
        else:
            # E.g. a scenario pressed Enter in a form instead of clicking Save; the next scenarios repeated it
            # unless the writer is told which setup step did not work on this app.
            step = str(item.get("failed_step") or "")
            await remember(db, run, FACT_KIND, f"setup:{step[:120]}", {
                "fact": f"setup step failed on this app's base: {step} ({str(item.get('error') or '')[:160]})"})


async def app_facts(db: AsyncSession, run: WorkflowRun) -> list[str]:
    """What earlier runs learned about this app for the scenario writer (the run memory's ``app_fact`` entries)."""
    from ..run_memory.store import app_of, memory_of, record_of

    if not getattr(run, "repository", None):
        return []
    memory = memory_of(await record_of(db, run), app_of(run))
    return [str(item.get("fact") or "") for item in memory.get(FACT_KIND, []) if item.get("fact")]


async def writer_notes(db: AsyncSession, run: WorkflowRun) -> str:
    """The scenario writer's notes: the platform's hints (stacks.json ``general.scenario_hints``) and the app facts."""
    from ...engineering_knowledge.stacks import built_in

    hints = [str(item) for item in dict(built_in().get("general") or {}).get("scenario_hints") or []]
    notes = [*hints, *await app_facts(db, run)]
    if not notes:
        return ""
    return ("\n\nHow scenarios use this app (platform hints and what earlier runs found on this app):\n"
            + "\n".join(f"- {item}" for item in notes))


async def keeps_data(db: AsyncSession, run: WorkflowRun) -> bool:
    """Whether the app keeps its data across a restart: its environment file's ``serve.persistent`` (default true),
    unless the run memory learned that it does not."""
    from ..run_memory.store import app_of, memory_of, record_of
    from ..workspace.spec import environment_for_run

    try:
        serve = dict(dict(await environment_for_run(db, run) or {}).get("serve") or {})
    except Exception:  # noqa: BLE001 - without the file the memory still answers
        serve = {}
    if serve.get("persistent") is False:
        return False
    if not getattr(run, "repository", None):
        return True  # no repository record holds a memory
    memory = memory_of(await record_of(db, run), app_of(run))
    return not any(item.get("key") == FACT_KEY for item in memory.get(FACT_KIND, []))


__all__ = ["DATA_LOST", "EVENT", "app_facts", "invalid_result", "keeps_data", "record", "writer_notes"]
