"""A repository whose suite is plain unittest proves its tasks in the pipeline: the device runs the declared command
verbosely (stack data ``test_runner.report_args``) and sends its whole output, which names every test's outcome."""

from __future__ import annotations

import pytest

from app.services.engineering_knowledge.stacks import all_report_args
from app.services.workflow_runs import pipeline, pipeline_report
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_pipeline_support import _at_pipeline

pytestmark = pytest.mark.usefixtures("scripted_pool")

COMMAND = "python3 -m unittest discover -s tests"
PROOFS = ["tests/test_shipping.py::ShippingTest::test_fee", "tests/test_shipping.py::ShippingTest::test_free"]
SUMMARY = "\n----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nOK\n"
VERBOSE = ("test_fee (test_shipping.ShippingTest.test_fee) ... ok\n"
           "test_free (test_shipping.ShippingTest.test_free)\nFree from 50.00. ... ok\n" + SUMMARY)


async def _report(db, monkeypatch, **result):
    run, session = await _at_pipeline(db, monkeypatch, commands_declared=[COMMAND])
    run.context = {**run.context, "task_list": [{"id": "T1", "text": "shipping fee", "proof": PROOFS[0],
                                                 "proofs": PROOFS, "status": "open"}]}
    view = pipeline.contract_view(run)
    body = {"node_id": view["node_id"], "entry": view["entry"], "results": [
        {"command": COMMAND, "exit_code": 0, "seconds": 0.1, "output_tail": SUMMARY, "junit_xml": None, **result}]}
    return view, run, await pipeline_report.record_report(db, run, body, session_id=session.id)


@pytest.mark.asyncio
async def test_the_verbose_report_of_a_unittest_suite_proves_its_tasks(db, monkeypatch):
    view, run, state = await _report(db, monkeypatch, ran=f"{COMMAND} -v", report_text=VERBOSE)
    assert view["report_args"] == all_report_args() and any(spec["add"] == "-v" for spec in view["report_args"])
    assert state == "green"
    assert "report_text" not in str(run.context.get("actions") or {})  # the whole output is read, never stored


@pytest.mark.asyncio
async def test_without_the_report_the_summary_alone_proves_nothing(db, monkeypatch):
    _view, run, state = await _report(db, monkeypatch)
    assert state == "red"
    assert f"{PROOFS[0]}: not run" in run.context["actions"]["pipeline"]["reason"]
