"""The answer evidence guard is proportionate: it never withholds an answer."""

from __future__ import annotations

import pytest

from app.services.answer_evidence.check import check_answer_evidence, mark_answer
from app.services.answer_evidence.evidence import collect_turn_evidence

GUIDELINES = "http://fake-confluence:8852/wiki/spaces/CHEF/pages/100004"
CHEF8 = "http://fake-jira:8851/browse/CHEF-8"


def _confluence_page() -> dict:
    return {
        "tool_name": "get_confluence_page",
        "result": {
            "title": "Coding guidelines",
            "source_url": GUIDELINES,
            "cite_as": f"[Coding guidelines]({GUIDELINES})",
            "content": "Branch names: feature/CHEF-123-short-name or bugfix/CHEF-123-short-name. Hotfix from the tag.",
        },
    }


def _jira_search() -> dict:
    return {
        "tool_name": "search_jira_tickets",
        "result": {"issues": [{"key": "CHEF-8", "source_url": CHEF8, "cite_as": f"[CHEF-8: Bug: Nutrition totals]({CHEF8})"}]},
    }


def _jira_comment() -> dict:
    return {"tool_name": "add_jira_comment", "result": {"success": True, "issue_key": "CHEF-8", "comment_id": "20001"}}


T12_DRAFT = f"""Your branch naming rule is documented in the CHEF space's Coding guidelines page, and it applies to every repository.

- Feature branches use `feature/CHEF-123-short-name` ([Coding guidelines]({GUIDELINES})).
- Bugfix branches use `bugfix/CHEF-123-short-name` ([Coding guidelines]({GUIDELINES})).
- Hotfix branches start from the last release tag and need a review by two people.

Let me know if you also want the commit message rules from the same page."""










def test_a_failed_write_is_no_executed_action() -> None:
    failed = {"tool_name": "add_jira_comment", "result": {"error": "403"}}
    assert collect_turn_evidence([_jira_search(), failed]).executed_writes == ()
    assert collect_turn_evidence([_jira_search(), _jira_comment()]).executed_writes == ("add_jira_comment",)






@pytest.mark.parametrize(
    ("row", "marked"),
    [
        (f"| feature | `feature/CHEF-123-x` ([Coding guidelines]({GUIDELINES})) |", False),
        ("| hotfix | starts from the last release tag with two reviewers |", True),
    ],
)
def test_a_table_row_is_marked_inside_its_last_cell(row: str, marked: bool) -> None:
    evidence = collect_turn_evidence([_confluence_page()])
    rows = [f"| bugfix | `bugfix/CHEF-123-x` ([Coding guidelines]({GUIDELINES})) |", row]
    answer = "Branch kinds from the guidelines:\n\n| kind | rule |\n|---|---|\n" + "\n".join(rows)
    check = check_answer_evidence(answer, evidence)
    last = mark_answer(answer, check, evidence).splitlines()[-1]
    assert last.endswith("_(no source)_ |") is marked and last.endswith("|")
