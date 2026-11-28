"""The report's pinned environment file and test runs: each command recorded as a test run, tasks by their proof."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .pipeline_results import _failed_tests, _file_audit, _test_run


def _pinned_file_audit(run: WorkflowRun, current: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    audit = _file_audit(dict(current["environment_file"]), report)
    from .workspace.contract_pin import changed_from_pin, pin

    if audit.get("file_state") == "ok" and changed_from_pin(run, str(audit.get("sha256") or "")):
        # The device ran a rewritten environment file, not the run's pinned contract.
        audit = {**audit, "file_state": "contract_changed", "file_errors": [
            f"the device ran {audit.get('file')} with sha256 {audit.get('sha256')}, but the run's contract is "
            f"{pin(run)['sha256']}: the environment file may not change during the run"]}
    return audit


def _record_test_runs(run: WorkflowRun, results: list[dict[str, Any]], tasks: list[Any]) -> dict[str, Any]:
    from .task_list import proofs_of
    from .test_runs import record_test_run

    proofs = [proof for task in tasks for proof in proofs_of(task)]
    seen: dict[str, Any] = {}
    for item in results:
        if item.get("skipped"):
            continue
        test_run = _test_run(run, item, proofs)
        record_test_run(run, test_run, node_id=run.current_node_id)
        item["failed_tests"] = _failed_tests(test_run)
        seen.update(dict(test_run.get("results") or {}))
        if item.get("rerun"):
            # The re-run of the failed tests, recorded as its own run: a flaky test's pass there is its result.
            again = _test_run(run, {**item, **item["rerun"], "command": item["command"]}, proofs)
            again["rerun_of_failed"] = True
            record_test_run(run, again, node_id=run.current_node_id)
            still = set(_failed_tests(again))
            item["failed_tests"] = [test for test in item["failed_tests"] if test in still or not item.get("flaky")]
            if item.get("flaky_again"):
                item["failed_tests"] = sorted({*item["failed_tests"], *item["flaky_again"]})
            seen.update(dict(again.get("results") or {}))
    return seen


async def _tasks_after_pipeline(db: AsyncSession, run: WorkflowRun, tasks: list[Any], missing_proofs: list[str], *,
                                green: bool) -> None:
    from . import task_status

    proven = {task["id"] for task in tasks if not any(entry.startswith(f"{task['id']} (")
                                                      for entry in missing_proofs)}
    moved = task_status.after_pipeline(tasks, proven, green=green, run_id=run.id)
    if moved != tasks:
        await task_status.store(db, run, moved)
