"""The Word gate enforces the same contract as the slide gate, on the plan."""

from app.services.office_identity import check_document_quality


def _clean_plan() -> list[dict]:
    return [
        {"kind": "title", "text": "Report", "source": "account_id"},
        {"kind": "heading", "level": 1, "text": "Summary", "source": "service_summary"},
        {"kind": "paragraph", "text": "232 resources."},
        {"kind": "heading", "level": 2, "text": "Detail", "source": "node_counts"},
        {"kind": "bullets", "items": [{"text": "9 subnets", "source": "x"}]},
        {"kind": "heading", "level": 1, "text": "Open points", "source": "planner"},
        {"kind": "marker", "text": "[DECISION: confirm owner]"},
    ]


def test_clean_plan_has_no_findings():
    assert check_document_quality(_clean_plan()) == []


def test_heading_level_skip_is_flagged():
    plan = [
        {"kind": "heading", "level": 1, "text": "A", "source": "s"},
        {"kind": "paragraph", "text": "x"},
        {"kind": "heading", "level": 3, "text": "C", "source": "s"},
        {"kind": "paragraph", "text": "y"},
        {"kind": "marker", "text": "[CHECK NUMBER: n]"},
    ]
    rules = {f["rule"] for f in check_document_quality(plan)}
    assert "heading_hierarchy_skip" in rules


def test_empty_section_is_flagged():
    plan = [
        {"kind": "heading", "level": 1, "text": "A", "source": "s"},
        {"kind": "heading", "level": 1, "text": "B", "source": "s"},
        {"kind": "paragraph", "text": "content"},
        {"kind": "marker", "text": "[SOURCE MISSING: x]"},
    ]
    findings = check_document_quality(plan)
    empty = [f for f in findings if f["rule"] == "empty_section"]
    assert empty and empty[0]["block_index"] == 0


def test_missing_source_on_a_claim_is_flagged():
    plan = [
        {"kind": "heading", "level": 1, "text": "A", "source": ""},
        {"kind": "paragraph", "text": "x"},
        {"kind": "marker", "text": "[DECISION: y]"},
    ]
    rules = {f["rule"] for f in check_document_quality(plan)}
    assert "missing_evidence_source" in rules


def test_no_open_points_is_flagged():
    plan = [
        {"kind": "title", "text": "R", "source": "s"},
        {"kind": "heading", "level": 1, "text": "A", "source": "s"},
        {"kind": "paragraph", "text": "x"},
    ]
    rules = {f["rule"] for f in check_document_quality(plan)}
    assert "no_open_points" in rules
