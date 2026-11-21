"""Writing a run's hands-on scenarios once (``step.generate_due``): the review model, then the step's next state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, WorkflowRun
from ....time_utils import utc_now
from ..records import record_event
from .step import CODE_SCENARIOS_FAILED, EVENT_REPORTED, GENERATING, PENDING, RED, SCENARIOS_KEY, _set, state


async def _write(db: AsyncSession, run: WorkflowRun, *, model_factory: Any) -> tuple[str, list[Any]]:
    """``(problem, scenarios)`` the review model writes for the run's change (no run lock is held)."""
    from ..graph import graph_for_run
    from ..review.call_inputs import _review_model, _working_copy
    from ..review.choice import review_choice
    from ..review.convergence import changed_paths
    from ..review.model import governed_review_model
    from ..review.reviewer_agent import reviewer_setup
    from .generate import scenario_task, write_scenarios

    setup = await reviewer_setup(db, run)
    choice = await review_choice(db, run, {}) if not isinstance(setup, str) else setup
    problem, scenarios = "", []
    if isinstance(setup, str) or isinstance(choice, str):
        problem = f"no model to write the scenarios: {setup if isinstance(setup, str) else choice}"
    else:
        model = await _review_model(model_factory or governed_review_model, db, run, setup, choice)
        changed = changed_paths(str(dict(dict(run.context or {}).get("device_change") or {}).get("patch") or ""))
        root = await _working_copy(db, run)
        task = await scenario_task(db, run, root, changed)
        from ...engineering_knowledge.stacks import for_project
        from .generate import app_root, screen_actions, ui_texts

        stacks = await for_project(db, await db.get(Project, run.project_id) if run.project_id else None)
        hands_on = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
        scenarios, problem, _usage = await write_scenarios(
            db, run, model, task, ui_texts(app_root(root, changed, stacks), stacks) if root is not None else [],
            screen_actions(root, changed, stacks) if root is not None else [],
            [str(item) for item in (hands_on.config.get("generic_actions") or [])] if hands_on is not None else [])
    return problem, scenarios


async def _scenarios_failed(db: AsyncSession, run: WorkflowRun, current: dict[str, Any], problem: str) -> None:
    # The platform's own scenario writer failed (its model, its setup or its answers);
    # nothing the building agent can change. The run pauses with the reason (cause platform) and Retry writes them
    # again, instead of a red round back to the agent.
    from ..limits import pause_run
    from ..states import PAUSE_RUNTIME_FAILED

    _set(run, {**current, "state": RED, "problem": problem, "reported_at": utc_now().isoformat()})
    record_event(db, run, EVENT_REPORTED, node_id=run.current_node_id, detail={"state": RED, "reason": problem})
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "code": CODE_SCENARIOS_FAILED, "resume": {"kind": "restart", "node_id": run.current_node_id},
        "message": (f"The platform could not write the hands-on scenarios: {problem}. The built change is not "
                    "at fault. Retry writes them again; if it repeats, check the review model's setup for this "
                    "Workspace.")})
    await db.commit()


async def generate(db: AsyncSession, run: WorkflowRun, *, model_factory: Any = None) -> bool:
    from ..graph import graph_for_run
    from ..records import lock_run
    from .generate import describe

    entry = state(run).get("entry")
    problem, scenarios = await _write(db, run, model_factory=model_factory)
    run = await lock_run(db, await db.get(WorkflowRun, run.id))
    current = state(run)
    if current.get("state") != GENERATING or current.get("entry") != entry:
        await db.rollback()
        return False
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if not scenarios:
        await _scenarios_failed(db, run, current, problem)
        return True
    run.context = {**dict(run.context or {}), SCENARIOS_KEY: scenarios}
    _set(run, {**current, "state": PENDING, **({"stale_before": utc_now().isoformat()} if current.get("stale_before")
                                                 else {})})  # after a regeneration: only passes from now on count
    record_event(db, run, "hands_on_scenarios_written", node_id=run.current_node_id,
                 detail={"count": len(scenarios), "scenarios": describe(scenarios)})
    from ..octryx.continuation import runtime_step_entered

    await runtime_step_entered(db, run, node)
    await db.commit()
    return True
