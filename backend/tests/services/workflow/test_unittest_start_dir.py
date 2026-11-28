"""``unittest discover -s tests`` names its modules from the start folder, so a gate that ignores the start folder sees
none of the confirmed tests. The outputs are real (Python 3.12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.workflow_checks.test_ids import Resolver
from app.services.workflow_checks.test_output import parse
from app.services.workflow_checks.test_results import confirmed_outcomes, evidence_unresolved
from app.services.workflow_checks.unittest_blocks import module_prefix

OUTPUTS = Path(__file__).parents[2] / "fixtures" / "unittest_output"
CONFIRMED = ["tests/test_pricing.py::PricingTest::test_discount_applies", "tests/test_pricing.py::PricingTest::test_total"]
RESOLVER = Resolver(files=["tests/test_pricing.py"])


@pytest.mark.parametrize(("command", "prefix"), [
    ("python3 -m unittest discover -s tests", "tests"),
    ("python -m unittest discover -v -s ./tests/", "tests"),
    ("python -m unittest discover --start-directory=src/tests -p 'test_*.py'", "src.tests"),
    ("python -m unittest discover tests 'test_*.py'", "tests"),
    ("python -m unittest discover -s tests -t .", ""),
    ("cd demo-shop && python3 -m unittest discover -s tests 2>&1 | tail -20", "tests"),
    ("python3 -m unittest", ""),
    ("python3 -m unittest tests.test_pricing", ""),
    ("python -m unittest discover -s /abs/tests", ""),
    ("pytest -q", ""),
])
def test_the_start_folder_comes_from_the_command(command, prefix):
    assert module_prefix(command) == prefix


def test_a_green_discover_run_reports_the_confirmed_tests():
    run = {**parse((OUTPUTS / "discover_green_v.txt").read_text(encoding="utf-8"), RESOLVER,
                   "python3 -m unittest discover -s tests -v").fields(), "all_green": True}
    assert set(run["results"]) == set(CONFIRMED) and not run.get("unresolved")
    assert all(outcomes for outcomes in confirmed_outcomes(run, CONFIRMED).values())
    assert evidence_unresolved(run, CONFIRMED) == []


def test_a_red_discover_run_without_v_names_the_failing_test_by_its_file():
    parsed = parse((OUTPUTS / "discover_red_plain.txt").read_text(encoding="utf-8"),
                   command="python3 -m unittest discover -s tests")
    assert parsed.results[CONFIRMED[0]] == {"outcome": "failed", "message": "AssertionError: 45.0 != 40.0"}
