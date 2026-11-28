"""A new module's tests are red while the module does not exist; demanding an assertion failure instead
pushed weak models to stub the class in the test file."""

from __future__ import annotations

from pathlib import Path

from app.services.workflow_checks.test_results import all_red, parse_test_output

OUTPUT = (Path(__file__).parents[2] / "fixtures" / "pytest_collection_module_missing.txt").read_text(encoding="utf-8")
TEST = "tests/test_repository.py::test_schema_init"


def test_the_collection_error_carries_its_cause_and_counts_as_red():
    results = parse_test_output(OUTPUT)
    assert "ModuleNotFoundError" in results["tests/test_repository.py"]["message"]
    assert all_red({"results": results}, [TEST]) == (True, "")


def test_another_error_before_the_assertions_stays_not_red():
    results = {"tests/test_repository.py": {"outcome": "error", "message": "NameError: name 'x' is not defined",
                                            "scope": "collection"}}
    ok, why = all_red({"results": results}, [TEST])
    assert not ok and "errors before its assertions" in why
