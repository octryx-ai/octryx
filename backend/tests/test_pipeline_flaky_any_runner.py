"""A red non-pytest run whose failed test passes when the device runs it
again alone (stack data ``test_runner.rerun``) is flaky under the same rule as pytest: not counted the first time."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge.stacks import rerun_specs
from app.services.workflow_runs import pipeline, pipeline_report
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import COMMANDS, _at_pipeline

pytestmark = pytest.mark.usefixtures("scripted_pool")

TEST = "test/features/brews/brews_performance_test.dart::1000 brews: scrolling frames build and lay out within 16 ms"
RED = ("00:27 +362 -1: /x/coffee/test/features/brews/brews_performance_test.dart: 1000 brews: scrolling frames build "
       "and lay out within 16 ms [E]\n00:28 +370 -1: Some tests failed.\n")


def test_flutter_declares_how_a_failed_test_runs_again_alone():
    [spec] = rerun_specs()
    assert ["flutter", "test"] in spec["commands"] and spec["single"] == [
        "flutter", "test", "{file}", "--plain-name", "{name}"]
    import re

    match = re.search(spec["failed"], RED, re.MULTILINE)
    assert match["file"].endswith("brews_performance_test.dart") and match["name"].startswith("1000 brews")


@pytest.mark.asyncio
async def test_a_failed_test_that_passes_alone_is_flaky_and_the_pipeline_green(db, monkeypatch):
    run, session = await _at_pipeline(db, monkeypatch)
    view = pipeline.contract_view(run)
    assert view["reruns"] == rerun_specs()  # the device learns how to re-run a non-pytest runner
    body = {"node_id": view["node_id"], "entry": view["entry"], "results": [
        {"command": COMMANDS[0], "exit_code": 0, "seconds": 3.0, "output_tail": "3 passed in 0.1s", "junit_xml": None},
        {"command": COMMANDS[1], "exit_code": 1, "seconds": 30.0, "output_tail": RED, "junit_xml": None,
         "rerun": {"exit_code": 0, "seconds": 4.0, "output_tail": "00:03 +1: All tests passed!", "junit_xml": None,
                   "tests": [TEST]}, "flaky": [TEST]}]}
    assert await pipeline_report.record_report(db, run, body, session_id=session.id) == "green"
    assert run.context["pipeline_flaky"] == {TEST: 1}
