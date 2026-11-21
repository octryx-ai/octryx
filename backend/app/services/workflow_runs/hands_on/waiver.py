"""An admin waives hands-on scenarios of one run for every further pass.

A run's fix can be verified in the running app (its scenario green) while other scenarios stay red for reasons that
are not the run's, e.g. a generated scenario expected a text the page never shows, and a regression scenario failed
on another open bug (persistence). The hands_on → fix loop could then never end; a one-off routing past the step
holds only one pass. The action ``waive_hands_on_scenarios`` ({scenarios, reason}, a platform admin) keeps the waiver
on the run (``context.hands_on_waived``, an event): the device no longer runs a waived generated scenario, a waived
repository scenario's result does not count, and the report lists each as "waived by admin (reason)". Not a silent
pass: the reason and the person stay on the run.
"""

from __future__ import annotations

from typing import Any

from ....time_utils import utc_now

WAIVED_KEY = "hands_on_waived"
EVENT_WAIVED = "hands_on_scenarios_waived"
MAX_WAIVED = 50


def waived(run: Any) -> dict[str, dict[str, Any]]:
    return {str(key): dict(value) for key, value in dict(dict(run.context or {}).get(WAIVED_KEY) or {}).items()
            if isinstance(value, dict)}


def waive(run: Any, scenarios: list[str], reason: str, *, user_id: str) -> dict[str, dict[str, Any]]:
    """Add the waivers; returns the run's waivers."""
    from ..records import WorkflowRunError

    names = [str(item).strip()[:200] for item in scenarios if str(item).strip()][:MAX_WAIVED]
    reason = str(reason or "").strip()[:500]
    if not names or not reason:
        raise WorkflowRunError("waiver_invalid", "Name the scenarios and the reason for waiving them.", 422)
    current = waived(run)
    for name in names:
        current[name] = {"reason": reason, "by": user_id, "at": utc_now().isoformat()}
    run.context = {**dict(run.context or {}), WAIVED_KEY: current}
    return current


def waived_result(scenario_id: str, title: str, waiver: dict[str, Any]) -> dict[str, Any]:
    return {"id": scenario_id, "title": title, "passed": True, "waived": f"waived by admin ({waiver.get('reason')})",
            "screenshots": []}


__all__ = ["EVENT_WAIVED", "WAIVED_KEY", "waive", "waived", "waived_result"]
