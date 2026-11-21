"""The reviewer's verdict is found in its answer even when other JSON comes first."""

from app.services.workflow_runs.review.model import answer_object
from app.services.workflow_runs.review.verdict import parse_verdict


def test_the_verdict_object_wins_over_a_quoted_finding_or_example_before_it():
    text = ('The card styles look fine. One finding: {"severity": "low", "file": "a.css", "line": 3, "fix": "x"}.\n'
            'Final answer:\n```json\n{"verdict": "changes", "summary": "One gap.", "findings": [\n'
            '  {"severity": "high", "file": "src/benchmark/web/index.html", "line": 9, "fix": "Link layout.css"},\n'
            ']}\n```')
    value = answer_object(text)
    assert value["verdict"] == "changes"  # the trailing comma is tolerated
    assert parse_verdict(value).findings[0].file == "src/benchmark/web/index.html"


def test_css_braces_and_an_audit_object_are_handled():
    assert answer_object('.card { border-radius: 12px; }\n{"audit": [], "answers": []}') == {"audit": [], "answers": []}
    assert answer_object('no json here') is None
    assert answer_object('{"other": 1}') == {"other": 1}  # no verdict anywhere: the first object
