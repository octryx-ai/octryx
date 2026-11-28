"""The confirmed-test checks judge the last run that names tests, so a system test script running after `flutter test`
does not make the confirmed Dart tests look missing."""

from __future__ import annotations

from app.services.workflow_checks.library import judged_run

UNIT = {"source": "pipeline", "command": "flutter test", "all_green": True, "suite_passed": 20,
        "results": {"test/features/brews/brew_form_test.dart::grind stepper": {"outcome": "passed"}}}
SYSTEM = {"source": "pipeline", "command": "python3 system_test/run_system_test.py", "all_green": True, "results": {}}


def test_a_pipeline_system_test_script_after_the_suite_is_not_the_judged_run():
    assert judged_run([UNIT, SYSTEM]) is UNIT


def test_an_agent_run_without_results_is_still_judged_and_so_is_a_lone_script():
    agent = {"source": "octryx", "all_green": True, "results": {}}
    assert judged_run([UNIT, agent]) is agent  # the agent's own unreadable run stays the platform's problem to report
    assert judged_run([SYSTEM]) is SYSTEM
    unresolved = {**SYSTEM, "unresolved": [{"raw": "x", "outcome": "failed"}]}
    assert judged_run([UNIT, unresolved]) is unresolved
