"""A flat (or empty) repository runs the TDD phases: top-level tests and modules are allowed where nothing else fits."""

from __future__ import annotations

from app.services.workflow_runs.octryx.phase_view import how_to_run_tests
from app.services.workflow_runs.octryx.shell_rules import strict_shell_allows
from app.services.workflow_runs.path_rules import blocked_paths
from app.services.workflow_runs.protected_paths import (
    KIND_NEW_FILE,
    KIND_TEST_CONFIG,
    KIND_TEST_FILE,
    is_flat_repository,
    protected_kind,
)

TESTS_FIRST = ["tests/**", "test/**", "**/tests/**", "**/test/**", "**/test_*", "**/*_test.*", "**/*Test.*"]
CREATE = ["src/**", "lib/**", "app/**", "pkg/**", "internal/**", "cmd/**"]


def test_a_top_level_test_file_is_a_test_path_of_the_tests_first_phase():
    assert blocked_paths(["test_greeting.py", "tests/test_x.py"], TESTS_FIRST) == []
    assert blocked_paths(["greeting.py"], TESTS_FIRST) == ["greeting.py"]


def test_a_flat_repository_creates_its_module_at_the_top_level_and_nothing_else_opens(tmp_path):
    assert is_flat_repository(tmp_path, CREATE)
    (tmp_path / "src").mkdir()
    assert not is_flat_repository(tmp_path, CREATE)

    def kind(path: str, flat: bool) -> str | None:
        return protected_kind(path, confirmed_files=["test_greeting.py"], protect_tests=True, exists=False,
                              create=CREATE, flat=flat)

    assert kind("greeting.py", flat=False) == KIND_NEW_FILE
    assert kind("greeting.py", flat=True) is None
    assert kind("test_other.py", flat=True) == KIND_TEST_FILE
    assert kind("conftest.py", flat=True) == KIND_TEST_CONFIG
    assert kind("pkg/deep/new.py", flat=True) is None


def test_the_device_shell_runs_pytest_version_and_the_contract_says_how_to_run_tests():
    prefixes = (("pytest",), ("python", "-m", "pytest"), ("python3", "-m", "pytest"))
    for command in ("python3 -m pytest --version", "python -m pytest -q", "pytest --collect-only -q"):
        assert strict_shell_allows(command, runs_tests=True, test_prefixes=prefixes), command
    assert not strict_shell_allows("python -m pytest -p evil", runs_tests=True, test_prefixes=prefixes)
    undeclared = how_to_run_tests(None)
    assert "python -m pytest -v" in undeclared and "run_test_suite" in undeclared


def test_how_to_run_tests_follows_the_repositorys_stack():
    flutter = how_to_run_tests({"test": "export PUB_CACHE=$PWD/.pub-cache; flutter test"})
    assert "`export PUB_CACHE=$PWD/.pub-cache; flutter test`" in flutter and "--reporter json" in flutter
    assert "pytest" not in flutter
    file = how_to_run_tests({"source": "environment_file", "environment_file": "app/.octryx/environment.json",
                             "test": ""})
    assert "app/.octryx/environment.json" in file and "pytest" not in file
    python = how_to_run_tests({"test": ".venv/bin/python -m pytest -v"})
    assert "-v names every test" in python and "flutter" not in python


def test_a_pytest_run_that_names_no_test_is_asked_again_with_v():
    from app.services.workflow_runs.octryx.pytest_args import pytest_without_test_names

    prefixes = (("pytest",), ("python", "-m", "pytest"), ("python3", "-m", "pytest"))
    assert pytest_without_test_names(".venv/bin/python -m pytest -q", prefixes)
    assert pytest_without_test_names("pytest", prefixes)
    assert not pytest_without_test_names(".venv/bin/python -m pytest -v", prefixes)
    assert not pytest_without_test_names("pytest -q -rA", prefixes)
    assert not pytest_without_test_names("ls -la", prefixes)


def test_test_writing_phases_are_told_to_import_the_code_and_never_stub_it():
    from app.services.workflow_runs.octryx.phase_view import _writes_or_plans_tests
    from app.services.workflow_runs.run_texts import run_text

    assert "Never define, stub or copy the code under test" in run_text("contract.new_tests")
    tests_first = {"workflow_contract": {"path_rules": {"write": TESTS_FIRST}}}
    implement = {"workflow_contract": {"path_rules": {"write": ["src/**", "**/*.py"]}}}
    assert _writes_or_plans_tests(tests_first, {})
    assert _writes_or_plans_tests({}, {"output": {"kind": "test_contract"}})
    assert not _writes_or_plans_tests(implement, {})
