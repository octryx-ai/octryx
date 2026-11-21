"""The structured analysis contract — strict parsing, citation check, rendering."""

from __future__ import annotations

import json

import pytest

from app.services.work_item_analysis.contract import (
    MAX_ITEMS,
    MAX_NOTE_CHARS,
    AnalysisContractError,
    check_citations,
    parse_analysis,
    render_note,
)
from tests.work_item_analysis.support import MANUAL_PAGE, analysis


def test_a_fenced_answer_is_accepted_and_unknown_keys_dropped():
    parsed = parse_analysis("```json\n" + json.dumps({**analysis(), "extra": "x"}) + "\n```")
    assert "extra" not in parsed and parsed["likely_cause"]["confidence"] == "medium"


@pytest.mark.parametrize("change", [
    {"likely_cause": {"text": "x", "confidence": "certain"}},
    {"likely_cause": "x"},
    {"summary": ""},
    {"evidence": [{"claim": "x", "source": {"kind": "blog", "title": "t", "locator": "l"}}]},
    {"evidence": [{"claim": "x", "source": {"kind": "manual", "title": "t", "locator": ""}}]},
    {"evidence": "page 4"},
    {"next_steps": [1]},
    {"similar_tickets": [{"url": "u"}]},
])
def test_a_malformed_answer_is_refused(change):
    with pytest.raises(AnalysisContractError) as refused:
        parse_analysis(json.dumps(analysis(**change)))
    assert refused.value.code == "analysis_invalid"


def test_lists_are_capped_and_citations_checked_against_tool_output():
    many = analysis(next_steps=[f"step {n}" for n in range(30)],
                    similar_tickets=[{"key": "INC0000101", "url": None, "why": "same error"},
                                     {"key": "INC9999999", "url": None, "why": "made up"}])
    parsed = check_citations(parse_analysis(json.dumps(many)), [f"... {MANUAL_PAGE} ... inc0000101 ..."])
    assert len(parsed["next_steps"]) == MAX_ITEMS
    assert [ticket["verified"] for ticket in parsed["similar_tickets"]] == [True, False]
    assert parsed["evidence"][0]["verified"] is True


def test_no_evidence_at_all_is_allowed_and_said_plainly():
    parsed = check_citations(parse_analysis(json.dumps(analysis(evidence=[]))), [])
    note = render_note(parsed, template="incident_analysis_v1")
    assert "Evidence: none found" in note and "written by an agent" in note


def test_the_note_is_bounded():
    huge = analysis(next_steps=["x" * 400] * MAX_ITEMS, open_questions=["y" * 400] * MAX_ITEMS,
                    affected_components=["z" * 400] * MAX_ITEMS)
    parsed = check_citations(parse_analysis(json.dumps(huge)), [MANUAL_PAGE])
    assert len(render_note(parsed, template="t")) <= MAX_NOTE_CHARS
