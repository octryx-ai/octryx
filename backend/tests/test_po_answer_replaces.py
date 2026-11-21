"""A product owner answer can replace earlier ones; replaced answers stay for the audit but reach neither the
reviewer nor the agent (otherwise the reviewer keeps "PO answer 2: drift" high after answer 3 replaced it)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.workflow_runs.po_answers import _record_po_answer
from app.services.workflow_runs.review.evidence import product_owner_answers


def test_a_replacing_answer_hides_the_replaced_ones_from_the_review_and_keeps_them_on_the_run():
    run = SimpleNamespace(context={})
    _record_po_answer(run, "Use drift for every record.", user_id="u1")
    _record_po_answer(run, "Last round: drift with its web backend.", user_id="u1")
    _record_po_answer(run, "Drift is its own story; keep the web fix.", user_id="u1", replaces=[1, 2, 9, "x"])
    assert product_owner_answers(run) == ["Drift is its own story; keep the web fix."]
    answers = run.context["po_answers"]
    assert [item.get("replaced_by") for item in answers] == [3, 3, None]  # out-of-range and non-numbers ignored
    _record_po_answer(run, "Also fix the Zone lookup.", user_id="u1")
    assert product_owner_answers(run) == ["Drift is its own story; keep the web fix.", "Also fix the Zone lookup."]


def test_the_action_request_accepts_replaces():
    from app.api.routes._workflow_run_http import RunActionRequest

    body = RunActionRequest(action="continue", reason="new decision", replaces=[1, 2])
    assert body.replaces == [1, 2]
