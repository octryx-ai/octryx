"""Every failed check of a Stop says what to do about it: "Phase 'Reproduce' is not done: The test suite ran."
names neither the tool nor the way."""

from types import SimpleNamespace

from app.services.prompt_catalog.seeds.run import SPECS
from app.services.workflow_runs.octryx.check_remedies import line, missing, remedy_types

CONTRACT = {"environment_pin": {"environment": {"test": "python3 -m unittest discover -s tests"}}}


def test_every_check_type_a_stop_can_report_has_a_remedy_text():
    keys = {spec.key: spec for spec in SPECS}
    for kind in remedy_types():
        spec = keys.get(f"run.remedy.{kind}")
        assert spec is not None and spec.seed.strip(), kind


def test_the_stop_names_the_tool_and_the_declared_command():
    checks = [{"type": "tool_called", "params": {"tools": ["run_test_suite"]}, "description": "The test suite ran"}]
    failed = [SimpleNamespace(type="tool_called", description="The test suite ran")]
    text = line(failed[0], checks, CONTRACT)
    assert text.startswith("The test suite ran: call run_test_suite")
    assert "`python3 -m unittest discover -s tests`" in text
    green = SimpleNamespace(type="test_command_passed", description="The last test run passed")
    assert "run the declared test command `python3 -m unittest discover -s tests` after your last change" in missing(
        [failed[0], green], checks, CONTRACT)


def test_without_a_declared_command_and_for_an_unknown_type_the_text_stays_honest():
    reproduces = SimpleNamespace(type="reproduces", description="The bug reproduces")
    assert "run `the repository's test command`" in line(reproduces, [], {})
    assert line(SimpleNamespace(type="custom_x", description="Something custom"), [], {}) == "Something custom"
