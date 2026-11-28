"""A confirmed test that was only reformatted on the device is intact."""

from __future__ import annotations

from hashlib import sha256

import pytest

from app.services.workflow_runs.octryx.facts import record_facts
from app.services.workflow_runs.octryx.format_only import same_program
from app.services.workflow_runs.test_runs import confirmed_test_drift
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_octryx_hardening import _confirmed
from tests.workflow_run_octryx_support import CONFIRMED

pytestmark = pytest.mark.usefixtures("scripted_pool")

CONFIRMED_TEXT = ("import unittest\n\n\nclass TotalsTest(unittest.TestCase):\n"
                  "    def test_half_up(self):\n        self.assertEqual(round_half_up(2.5), 3)\n")
REFORMATTED = ("import unittest\n\n\nclass TotalsTest(unittest.TestCase):\n"
               "    def test_half_up(self):\n        self.assertEqual(\n            round_half_up(2.5),\n"
               "            3,\n        )\n")
CHANGED = CONFIRMED_TEXT.replace("3)", "2)")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


def _report(run, text: str, *, sent: str | None = None) -> None:
    digest = "sha256:" + sha256(text.encode()).hexdigest()
    facts = {"node_id": run.current_node_id, "entry": run.node_state["entry"], "checked_files": [CONFIRMED],
             "confirmed_test_digests": {CONFIRMED: digest}, "confirmed_test_texts": {CONFIRMED: sent or text}}
    assert record_facts(run, facts) is True


@pytest.mark.asyncio
async def test_reformatted_is_intact_and_a_changed_assertion_is_not(db):
    assert same_program(CONFIRMED_TEXT, REFORMATTED, CONFIRMED)  # what the edit guard lets through
    run, *_ = await _confirmed(db)
    _report(run, CONFIRMED_TEXT)  # the baseline after the confirmation
    _report(run, REFORMATTED)
    assert confirmed_test_drift(run) == []
    _report(run, CHANGED)
    [drift] = confirmed_test_drift(run)
    assert f"its file {CONFIRMED} changed on the device after it was confirmed" in drift


@pytest.mark.asyncio
async def test_a_text_that_is_not_the_reported_content_proves_nothing(db):
    run, *_ = await _confirmed(db)
    _report(run, CONFIRMED_TEXT)
    _report(run, CHANGED, sent=REFORMATTED)  # the digest says changed; a mismatching text cannot vouch for it
    assert confirmed_test_drift(run)
