"""The answer evidence guard is proportionate: it never withholds an answer.

A guard that withholds every answer whose introduction or closing remark has no link of its own hides right,
linked drafts; after a written Jira comment the person would only see "withheld". An answer cites where its
information comes from, but not every sentence needs a link. The drafts below are real model drafts
(bridge log ``calls.jsonl``), shortened.
"""

from __future__ import annotations

import pytest

from app.services.answer_evidence.check import check_answer_evidence, mark_answer
from app.services.answer_evidence.decision import ACTION_ACCEPT, ACTION_MARK, ACTION_REMIND, decide_answer_evidence
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


def _decide(content: str, history: list[dict], *, reminders: int = 0, user: str = "Wie lautet unsere Regel?"):
    return decide_answer_evidence(
        content=content, turn_tool_history=history, user_message=user, reminders=reminders,
        capability_type="diagnosis", sub_agent_depth=0,
    )


def test_t12_intro_and_closing_need_no_link_and_only_the_uncited_claim_is_marked() -> None:
    decision = _decide(T12_DRAFT, [_confluence_page()])

    # No reminder, no refusal: the answer links its source, so it is delivered at once.
    assert decision.action == ACTION_MARK
    assert (decision.record["cited_count"], decision.record["uncited_count"]) == (2, 1)
    lines = decision.content.splitlines()
    assert lines[0].startswith("Your branch naming rule is documented") and "(no source)" not in lines[0]
    assert lines[-1].startswith("Let me know") and "(no source)" not in lines[-1]
    hotfix = next(line for line in lines if line.startswith("- Hotfix"))
    assert hotfix.endswith("_(no source)_")
    assert all("(no source)" not in line for line in lines if "Feature" in line or "Bugfix" in line)


def test_a_fully_cited_answer_with_a_framing_intro_passes_unchanged() -> None:
    cited = T12_DRAFT.replace(
        "need a review by two people.", f"need a review by two people ([Coding guidelines]({GUIDELINES})).")
    decision = _decide(cited, [_confluence_page()])
    assert decision.action == ACTION_ACCEPT and decision.record["evidence_guard"] == "passed"


def test_t21_a_written_comment_is_never_withheld_or_marked() -> None:
    confirmation = (
        "The comment is on **CHEF-8** (\"Bug: Nutrition totals rounded wrongly\"). Jira accepted it (HTTP 201, comment "
        "ID 20001) with the text you specified: \"Fix ist im Commit CHEF-8 auf main.\""
    )
    decision = _decide(confirmation, [_jira_search(), _jira_comment()])
    assert decision.action == ACTION_ACCEPT and decision.record["evidence_guard"] == "passed"


def test_a_failed_write_is_no_executed_action() -> None:
    failed = {"tool_name": "add_jira_comment", "result": {"error": "403"}}
    assert collect_turn_evidence([_jira_search(), failed]).executed_writes == ()
    assert collect_turn_evidence([_jira_search(), _jira_comment()]).executed_writes == ("add_jira_comment",)


def test_t06_an_answer_that_links_nothing_gets_one_reminder_then_is_delivered() -> None:
    draft = "**CHEF-16 reports a functional bug: the Login button does nothing on Safari 18.1.** It is To Do, priority Medium."
    history = [{"tool_name": "get_jira_ticket", "result": {"key": "CHEF-16", "source_url": "http://fake-jira:8851/browse/CHEF-16"}}]

    assert _decide(draft, history).action == ACTION_REMIND
    after = _decide(draft, history, reminders=1)
    assert after.action == ACTION_MARK and after.content.startswith(draft)
    assert "No source linked" in after.content and "http://fake-jira:8851/browse/CHEF-16" in after.content


def test_a_question_back_needs_no_link() -> None:
    question = "Which of the two pages do you mean, the release process or the coding guidelines page?"
    assert _decide(question, [_confluence_page()]).action == ACTION_ACCEPT


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
