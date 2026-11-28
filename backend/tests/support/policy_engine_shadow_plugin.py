"""Shadow equality across the regression suites."""

from __future__ import annotations

import pytest

from app.services.policy_engine.decision_log import clear_decision_buffer
from app.services.policy_engine.draft_shadow import reset_draft_impact
from app.services.policy_engine.engine import clear_caches
from app.services.policy_engine.principals import clear_principal_cache
from app.services.policy_engine.runtime import reset_policy_runtime
from app.services.policy_engine.shadow import OUTCOME_ERROR, OUTCOME_MISMATCH, decision_counters, reset_shadow_state
from app.services.policy_engine.workspace_facts import clear_workspace_facts_cache

STRICT_MODULES = frozenset({
    "test_classification_policy_defaults",
    "test_classification_policy_matrix",
    "test_classification_policy_views",
    "test_gateway_reroute",
    "test_inbound_model_picker",
    "test_policy_engine_hooks",
    "test_work_coding_governance",
})

_REPORT: dict[str, dict[str, int]] = {}
_TOTALS: dict[str, int] = {}


def _reset() -> None:
    reset_policy_runtime()
    reset_shadow_state()
    clear_decision_buffer()
    clear_principal_cache()
    clear_workspace_facts_cache()
    reset_draft_impact()
    clear_caches()


@pytest.fixture(autouse=True)
def policy_engine_shadow_equality(request):
    _reset()
    yield
    counters = decision_counters()
    totals: dict[str, int] = {}
    bad: dict[str, int] = {}
    for point, outcomes in counters.items():
        for outcome, count in outcomes.items():
            totals[outcome] = totals.get(outcome, 0) + count
            if outcome in (OUTCOME_MISMATCH, OUTCOME_ERROR) and count:
                bad[f"{point}.{outcome}"] = count
    # user_properties travel with the report, so the xdist controller can sum what its workers saw.
    request.node.user_properties.append(("cedar_shadow", {"totals": totals, "bad": bad}))
    _reset()
    if bad and request.module.__name__.rsplit(".", 1)[-1] in STRICT_MODULES:
        pytest.fail(f"Cedar shadow disagreed with the legacy decision: {bad}")


def pytest_runtest_logreport(report) -> None:
    if report.when != "teardown":
        return
    for name, value in report.user_properties:
        if name != "cedar_shadow":
            continue
        for outcome, count in value["totals"].items():
            _TOTALS[outcome] = _TOTALS.get(outcome, 0) + count
        if value["bad"]:
            _REPORT[report.nodeid] = value["bad"]


def pytest_terminal_summary(terminalreporter) -> None:
    if not _TOTALS:
        return
    terminalreporter.section("Cedar shadow equality")
    terminalreporter.write_line("outcomes: " + ", ".join(f"{key}={value}" for key, value in sorted(_TOTALS.items())))
    for nodeid, counts in sorted(_REPORT.items()):
        terminalreporter.write_line(f"{nodeid}: {counts}")
