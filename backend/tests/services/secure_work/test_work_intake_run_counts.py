"""An intake run's honest counts: items left by the per-run limit or paging are pending for the next run (never
"filtered out"), and the automation label only counts the items the agent may start; it never filters."""

from __future__ import annotations

from app.services.secure_work.intake.run_counts import run_counts


def _item(*labels: str) -> dict:
    return {"labels_json": list(labels)}


def test_a_limited_page_reports_the_rest_as_pending_next_run():
    source = {"source_count": 120, "source_complete": False, "metadata": {"returned": 50, "requested_limit": 50}}
    counts = run_counts(normalized=[_item("OCTRYX"), _item("octryx", "human-only"), _item()], source=source,
                        sync_options={"automation_labels": ["octryx"], "automation_mode": "direct"})
    assert counts["pending_next_run"] == 70 and counts["more_pending"] is True
    assert counts["automation"] == {"labels": ["octryx"], "matching": 1, "mode": "direct"}


def test_a_complete_source_has_nothing_pending_and_an_unknown_total_is_only_flagged():
    complete = run_counts(normalized=[], source={"source_count": 3, "source_complete": True,
                                                 "metadata": {"returned": 3}}, sync_options={})
    assert (complete["pending_next_run"], complete["more_pending"]) == (None, False)
    assert complete["automation"]["labels"] == ["octryx"] and complete["automation"]["mode"] == "needs_review"
    cloud = run_counts(normalized=[], source={"source_count": 50, "source_complete": False,
                                              "metadata": {"returned": 50}}, sync_options=None)
    assert (cloud["pending_next_run"], cloud["more_pending"]) == (None, True)
