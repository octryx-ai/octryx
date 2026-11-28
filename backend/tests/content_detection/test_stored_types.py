from __future__ import annotations

from typing import get_args

import pytest

from app.services.content_detection.custom_definitions import CHECKS
from app.services.content_detection.custom_validation import check_detector_set
from app.services.content_detection.scanner import ScanBudget, Segment, merge_reports, scan
from app.services.content_detection.stored_types import (
    Confidence,
    CustomCheck,
    CustomMaskStyle,
    ScanSummary,
    StoredDetectorSet,
)
from app.services.content_detection.vocabulary import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CUSTOM_MASK_STYLES
from tests.typed_dict_support import shape_problems

EMAIL = "jane.doe@example.org"
KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


@pytest.mark.parametrize(("segments", "budget"), [
    ([Segment(f"mail {EMAIL}, key {KEY}", "prompt"), Segment("10.0.0.7", "tool_result")], None),
    ([Segment("nothing here", "system")], None),
    ([Segment("x" * 50, "prompt"), Segment(f"mail {EMAIL}", "history")], ScanBudget(max_chars=10)),
    ([Segment("", "document", readable=False)], None),
    ([], None),
])
def test_every_scan_summary_is_a_scan_summary(segments, budget):
    report = scan(segments, budget=budget)
    assert shape_problems(report.summary(), ScanSummary, "summary") == []
    assert shape_problems(merge_reports([report, report]).summary(), ScanSummary, "merged") == []


def test_a_validated_detector_set_stores_a_stored_detector_set():
    raw = {"categories": [{"id": "contracts", "label": "Contracts"}],
           "detectors": [{"id": "custom.contract_no", "label": "Contract number", "category": "contracts",
                          "pattern": "CN-[0-9]{6}", "check": "mod10", "context_words": ["contract"],
                          "mask_style": "last4", "workspace_id": "ws-1"},
                         {"id": "custom.ticket", "label": "Ticket", "category": "pii", "pattern": "TK[0-9]{4}"}]}
    stored = check_detector_set(raw).to_json()
    assert shape_problems(stored, StoredDetectorSet, "detectors") == []
    assert check_detector_set(stored).to_json() == stored
    assert shape_problems(check_detector_set(None).to_json(), StoredDetectorSet, "empty") == []


def test_the_stored_vocabularies_are_the_constants_the_code_uses():
    assert get_args(CustomCheck) == CHECKS
    assert set(get_args(CustomMaskStyle)) == set(CUSTOM_MASK_STYLES)
    assert set(get_args(Confidence)) == {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}
