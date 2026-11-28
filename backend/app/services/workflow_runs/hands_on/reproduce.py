"""The bug flow's reproduce check (``hands_on.run`` with ``config.mode: reproduce``): before any fix, the device runs
only the bug's own scenarios (``tests/hands_on/bugs/<KEY>*.json`` the reproduce phase wrote) on the unchanged app."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

EXPECT_OPS = ("expect_text", "expect_no_text")
ROUTE_CANNOT_REPRODUCE = "cannot_reproduce"
ROUTE_SKIPPED = "skipped"
REPRO_SETUP_FAILED = "repro_setup_failed"


def verdict(report: dict[str, Any]) -> tuple[str, str]:
    state = str(report.get("state") or "")
    if state == "no_scenarios":
        return "no_scenarios", "the reproduce phase wrote no hands-on scenario for this bug"
    if state != "ran":
        return "setup_failed", str(report.get("problem") or state or "the app could not be used")[:1000]
    results = [item for item in report.get("scenarios") or [] if isinstance(item, dict)]
    if not results:
        return "setup_failed", "no scenario ran"
    symptom = [item for item in results if not item.get("passed") and (
        item["failed_symptom"] is True if "failed_symptom" in item else item.get("failed_op") in EXPECT_OPS)]
    if symptom:
        return "reproduced", "; ".join(f"{item.get('id')}: {item.get('error')}" for item in symptom)[:1000]
    if all(item.get("passed") for item in results):
        return "cannot_reproduce", "every scenario of the bug passed on the unchanged app"
    other = [item for item in results if not item.get("passed")]
    return "setup_failed", "; ".join(_setup_failure(item) for item in other)[:1000]


def _setup_failure(item: dict[str, Any]) -> str:
    where = f"{item.get('failed_op') or 'file'} failed"
    if "failed_symptom" in item and int(item.get("symptom_step", -1)) >= 0:
        where = (f"step {int(item.get('failed_step') or 0) + 1} ({item.get('failed_op')}) failed before the symptom "
                 f"steps from {int(item['symptom_step']) + 1} (marked \"symptom\": true, else the closing expects)")
    return f"{item.get('id')}: {where}: {item.get('error')}"


async def confirm_automatically(db: AsyncSession, run: WorkflowRun) -> None:
    from ..confirmation_payloads import _reproduction
    from ..confirmation_steps import _bind_confirmed_tests
    from ..graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    payload = {"subject": "reproduction", **await _reproduction(db, run, node)}
    if payload.get("tests"):
        await _bind_confirmed_tests(db, run, payload)


async def record(db: AsyncSession, run: WorkflowRun, node_config: dict[str, Any], report: dict[str, Any]
                 ) -> tuple[str, str, str]:
    outcome, why = verdict(report)
    if outcome == "reproduced":
        if node_config.get("confirm") is True:
            return "reproduced", ROUTE_SKIPPED, f"reproduced, a person confirms it: {why}"
        await confirm_automatically(db, run)
        return "reproduced", "succeeded", f"reproduced: {why}"
    if outcome == "cannot_reproduce":
        return "cannot_reproduce", ROUTE_CANNOT_REPRODUCE, why
    if outcome == "no_scenarios":
        return "no_scenarios", ROUTE_SKIPPED, why
    return REPRO_SETUP_FAILED, "failed", f"{REPRO_SETUP_FAILED}: {why}"


__all__ = ["EXPECT_OPS", "REPRO_SETUP_FAILED", "ROUTE_CANNOT_REPRODUCE", "record", "verdict"]
