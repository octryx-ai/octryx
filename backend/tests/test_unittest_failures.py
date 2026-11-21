"""A red unittest run shows its failing test for the reproduction confirmation, in either id form (a
`python3 -m unittest` run failing 40.0 != 45.0 must not read as "The last test run shows no test failing on an
assertion yet" without a Confirm). The outputs are real (Python 3.9 and 3.14, with and without -v), run in the app
folder demo-shop/."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.workflow_checks.test_output import parse
from app.services.workflow_runs.confirmation_payloads import _failing_tests, reproduction_tests, same_test

OUTPUTS = Path(__file__).parent / "fixtures" / "unittest_output"
TEST_ID = "tests/test_pricing.py::PricingTest::test_discount_applies"


@pytest.mark.parametrize("name", ["plain", "plain312", "verbose"])
def test_the_failed_unittest_is_a_failing_test_with_its_assertion(name):
    parsed = parse((OUTPUTS / f"{name}.txt").read_text(encoding="utf-8"), command="python3 -m unittest")
    assert parsed.results[TEST_ID]["outcome"] == "failed"
    assert parsed.results[TEST_ID]["message"] == "AssertionError: 40.0 != 45.0"
    assert "(failures=1)" not in parsed.results and not parsed.unresolved
    run = SimpleNamespace(context={"tests": {"runs": [{"source": "octryx", "all_green": False, **parsed.fields()}]}})
    assert _failing_tests(run) == [{"id": TEST_ID, "message": "AssertionError: 40.0 != 45.0"}]


def test_the_dotted_and_the_path_form_name_the_same_test():
    dotted = "tests.test_pricing.PricingTest.test_discount_applies"
    assert same_test(TEST_ID, dotted) and same_test(dotted, TEST_ID)
    assert same_test("demo-shop/" + TEST_ID, dotted)  # submitted from the repository root
    assert not same_test(TEST_ID, "tests.test_pricing.PricingTest.test_total")
    tests, symptom = reproduction_tests({"failing_tests": [{"id": TEST_ID, "message": "AssertionError: 40.0 != 45.0"}],
                                         "tests": [dotted]})
    assert tests == [TEST_ID] and symptom == "AssertionError: 40.0 != 45.0"
