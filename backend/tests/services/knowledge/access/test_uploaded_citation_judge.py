"""Independent acceptance: uploaded evidence must remain openable in chat."""


import pytest

from app.services.answer_evidence.check import check_answer_evidence
from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.answer_evidence.urls import normalize_url

WORKSPACE = "785b4554-bfbc-41f6-9f39-d408868134b2"
SOURCE = "11111111111141118111111111111111"
REVISION = "22222222222242228222222222222222"
ORIGINAL = f"/api/v1/workspaces/{WORKSPACE}/knowledge/sources/{SOURCE}/revisions/{REVISION}/original"


def evidence_with_url(url=ORIGINAL):
    return collect_turn_evidence([
        {"tool_name": "knowledge_search", "result": {
            "state": "ok", "evidence": [{"source_url": url, "source_title": "Runbook (revision 1)"}],
        }},
    ])


def test_uploaded_original_counts_as_evidence_and_requires_a_citation():
    evidence = evidence_with_url()
    assert evidence.evidence_bearing, "A governed uploaded original must not become unsourced"
    assert not check_answer_evidence("The drill runs on Tuesday.", evidence).satisfied
    answer = f"The drill runs on Tuesday ([Runbook]({ORIGINAL}))."
    checked = check_answer_evidence(answer, evidence)
    assert checked.satisfied and checked.cited_count == 1


def test_a_different_revision_is_not_a_source_of_this_turn():
    evidence = evidence_with_url()
    other = ORIGINAL.replace(REVISION, "33333333333343338333333333333333")
    checked = check_answer_evidence(f"The drill runs on Tuesday ([Runbook]({other})).", evidence)
    assert not checked.satisfied
    assert checked.invented_urls == (other,)


@pytest.mark.parametrize("url", [
    "/api/v1/workspaces/invalid/knowledge/sources/x/revisions/y/original",
    ORIGINAL + "?access_token=synthetic-placeholder",
    ORIGINAL + "?redirect=https://example.test",
    ORIGINAL.replace("/original", "/delete"),
    ORIGINAL.replace("/sources/", "/sources/../"),
    ORIGINAL.replace(SOURCE, "%2e%2e"),
    "//example.test" + ORIGINAL,
    "/api/v1/admin/users",
])
def test_original_recognition_does_not_allow_arbitrary_internal_routes(url):
    assert normalize_url(url) is None


