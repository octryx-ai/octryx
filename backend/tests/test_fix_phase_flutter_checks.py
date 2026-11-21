"""A bug's fix phase on a Flutter app in a subfolder: a piped green Dart run
counts, the system test rule never asks a phase that may not write tests, and the system test folder and the
change's files compare from the app folder."""

from app.services.workflow_runs.octryx.declared_commands import run_green
from app.services.workflow_runs.octryx.system_tests import phase_system_tests, system_folder, uncovered_change

APP = "coffee/flutter/claude"
SYSTEM = "python3 system_test/run_system_test.py"


def test_a_piped_dart_run_is_judged_by_its_closing_line():
    green = "00:49 +394: /w/app/test/x_test.dart: last\n00:49 +395: All tests passed!\n"
    red = "00:49 +393 -1: /w/app/test/x_test.dart: last\n00:49 +393 -1: Some tests failed.\n"
    assert run_green("flutter test 2>&1 | tail -3", "flutter test", succeeded=True, output=green)
    assert not run_green("flutter test 2>&1 | tail -3", "flutter test", succeeded=True, output=red)
    assert not run_green("flutter test 2>&1 | tail -3", "flutter test", succeeded=True, output="no summary here")


def test_a_phase_that_protects_tests_is_never_asked_for_a_system_test():
    environment = {"system_test": SYSTEM, "app_folder": APP}
    assert phase_system_tests("change", environment)["app_folder"] == APP
    assert phase_system_tests("change", environment, protects_tests=True) is None


def test_the_system_test_folder_and_the_change_compare_from_the_app_folder():
    assert system_folder(SYSTEM) == "system_test" and system_folder("pytest tests/system") == "tests/system"
    patch = (f"diff --git a/{APP}/lib/app/app_data.dart b/{APP}/lib/app/app_data.dart\n"
             f"diff --git a/{APP}/system_test/onboarding_scenarios.py b/{APP}/system_test/onboarding_scenarios.py\n")
    assert uncovered_change(SYSTEM, {"patch": patch}, APP) == ""
    only_code = f"diff --git a/{APP}/lib/app/app_data.dart b/{APP}/lib/app/app_data.dart\n"
    assert "adds or changes no system test in system_test/" in uncovered_change(SYSTEM, {"patch": only_code}, APP)


def test_a_phase_that_writes_only_tests_is_never_asked_for_a_green_system_test_run():
    """In the reproduce phase the bug is present by design, the phase writes tests only."""
    environment = {"system_test": SYSTEM, "app_folder": APP}
    reproduce = ["tests/**", "test/**", "**/tests/**", "**/test/**", "**/test_*", "**/*_test.*", "**/*_spec.*"]
    assert phase_system_tests("change", environment, write=reproduce) is None
    assert phase_system_tests("change", environment, write=["lib/**", "system_test/**"]) is not None


def test_a_phase_that_writes_only_tests_is_not_held_by_the_full_suite_rule():
    """In the reproduce phase its confirmed tests fail on the bug by design."""
    from types import SimpleNamespace

    from app.services.workflow_runs.octryx.declared_suite import declared_suite_result

    reproduce = ["tests/**", "test/**", "**/test_*", "**/*_test.*"]
    contract = {"phase": {"capability_class": "change", "path_rules": {"write": reproduce}},
                "preparation": {"environment": {"test": "flutter test"}}}
    edit = SimpleNamespace(tool_name="Edit", status="success", created_at=None,
                           parameters={"file_path": "test/x_test.dart"}, result={})
    assert declared_suite_result(contract, [edit], None) is None
    fix = {**contract, "phase": {"capability_class": "change", "path_rules": {"protect_confirmed_tests": True}}}
    assert declared_suite_result(fix, [edit], None) is not None
