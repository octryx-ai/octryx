"""PR review bot: ``@octryx ignore`` closes a finding and proposes a team rule; ``@octryx explain`` answers
in the thread from its own read-only run."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models import Project, UserLinkedAccount, WorkflowRun
from app.services.code_style.store import repository_profile
from app.services.pr_review_bot import comment_poll
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.explain import start_explain
from app.services.pr_review_bot.ignore import without_ignored
from app.services.pr_review_bot.rule_proposals import proposals
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.review.runner import run_due_reviews
from tests.pr_review_bot_flow_support import HEADERS, _origin, _payload, _tools, _workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_pr_review_bot_commands import _comment
from tests.workflow_run_review_support import ScriptedReviewer

pytestmark = pytest.mark.usefixtures("scripted_pool")

ONE = {"verdict": "changes", "summary": "Rounds wrongly.", "findings": [
    {"severity": "high", "file": "totals.py", "line": 3, "fix": "Use half-away-from-zero rounding."}]}


async def _reviewed(db, monkeypatch, tmp_path):
    clone, head = _origin(tmp_path)
    tools = _tools(monkeypatch, clone, post_github_pull_request_review=[
        {"status": "posted"}, {"status": "posted", "inline_ids": [4711]}, {"status": "posted"}])
    project_id, record, _hook = await _workspace(db, trigger="both")
    started = await start_review(db, project_id, pull_request_event(_payload(head), HEADERS), trigger=TRIGGER_WEBHOOK)
    assert await run_due_reviews(db, model_factory=ScriptedReviewer(ONE).factory) == 1
    run = await db.get(WorkflowRun, started.run_id)
    await db.refresh(run)
    from tests.phased_workflow_fixtures import admin_user

    owner = await admin_user(db)
    db.add(UserLinkedAccount(user_id=owner.id, platform="github", username="octryx-ai"))
    await db.flush()
    return project_id, record, run, head, owner, tools


def _provider(monkeypatch, head: str, comments: list[dict]) -> list:
    from app.tools.connectors.github_pr_review import _head

    pr = _head(_payload(head)["pull_request"])
    posts = []

    async def tools(tool, arguments, context):
        if tool == "list_github_pull_request_heads":
            return {"pull_requests": [pr], "comments": comments,
                    "permissions": {login: "write" for login in arguments.get("permissions_for") or []}}
        posts.append(arguments)
        return {"status": "posted"}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", tools)
    return posts


async def test_ignore_in_a_findings_thread_closes_it_turns_the_status_and_proposes_a_rule(db, monkeypatch, tmp_path):
    project_id, record, run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    facts = run.context["pr_review"]
    assert facts["posted"]["blocking"] == ["F1"] and facts["open_findings"][0]["comment_id"] == "4711"
    posts = _provider(monkeypatch, head, [
        _comment("c1", "octryx-ai", "@octryx ignore rounding is set by the bank", inline=True, in_reply_to="4711")])
    from app.services.pr_review_bot import bot_state

    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"ignored": 1}
    await db.refresh(run)
    facts = run.context["pr_review"]
    assert facts["open_findings"] == [] and facts["ignored"][0]["reason"] == "rounding is set by the bank"
    answer = posts[0]["thread_answers"][0]
    assert (answer["comment_id"], answer["resolve"]) == ("4711", True) and "🙈 Ignored by @octryx-ai" in answer["reply"]
    assert posts[1]["commit_status"]["state"] == "success" and posts[1]["commit"] == head  # it was the last blocking

    project = await db.get(Project, project_id)
    proposal = proposals(project)[0]
    assert proposal["rule"] == ("Do not report in totals.py: Use half-away-from-zero rounding. (reason: rounding is "
                                "set by the bank)")
    from app.api.routes.workflows import pr_review_bot as routes

    roles = {owner.id: "admin", "dev": "member"}

    async def role(_db, user_id, _project_id):
        return roles.get(user_id)

    monkeypatch.setattr(routes, "get_project_role_for_user", role)
    listed = await routes.get_rule_proposals(project_id, current_user=SimpleNamespace(id="dev"), db=db)
    assert listed["can_edit"] is False and listed["proposals"][0]["id"] == proposal["id"]
    refused = await routes.decide_rule_proposal(project_id, proposal["id"], "accept", None,
                                                current_user=SimpleNamespace(id="dev"), db=db)
    assert refused.status_code == 403
    accepted = await routes.decide_rule_proposal(project_id, proposal["id"], "accept", {
        "rule": "Rounding in totals.py follows the bank's rule; do not report it."}, current_user=owner, db=db)
    assert accepted["proposal"]["state"] == "accepted"
    assert repository_profile(record)["rules"] == "- Rounding in totals.py follows the bank's rule; do not report it."
    again = await routes.decide_rule_proposal(project_id, proposal["id"], "reject", None, current_user=owner, db=db)
    assert json.loads(again.body)["reason"] == "proposal_decided"


async def test_ignore_outside_a_findings_thread_closes_nothing(db, monkeypatch, tmp_path):
    _project_id, record, run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    posts = _provider(monkeypatch, head, [_comment("c2", "octryx-ai", "@octryx ignore")])
    from app.services.pr_review_bot import bot_state

    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"no_finding": 1}
    assert "reply in the thread of one of its findings" in posts[0]["comment"]
    await db.refresh(run)
    assert [item["id"] for item in run.context["pr_review"]["open_findings"]] == ["F1"]


def test_an_ignored_finding_does_not_come_back_on_a_later_pass():
    ignored = [{"id": "F1", "file": "totals.py", "line": 3}]
    findings = [{"id": "F4", "file": "totals.py", "line": 5, "severity": "high"},  # the same point, moved 2 lines
                {"id": "F5", "file": "totals.py", "line": 20, "severity": "high"},
                {"id": "CI1", "file": "(CI)", "line": 1, "source": "ci"}]
    assert [item["id"] for item in without_ignored(findings, ignored)] == ["F5", "CI1"]


async def test_explain_answers_in_the_thread_from_its_own_read_only_run(db, monkeypatch, tmp_path):
    project_id, _record, run, head, owner, tools = await _reviewed(db, monkeypatch, tmp_path)
    asked = []

    class Model:
        async def answer(self, *, system, user):
            from app.services.workflow_runs.review.model import ReviewAnswer, ReviewUsage

            asked.append((system, user))
            return ReviewAnswer({"answer": "`round()` rounds half to even: 2.5 becomes 2."},
                                ReviewUsage(model="review-model", provider="test", tokens_in=30, tokens_out=9))

    async def governed(_db, **_kwargs):
        return Model()

    monkeypatch.setattr("app.services.workflow_runs.review.model.governed_review_model", governed)
    pr = pull_request_event(_payload(head), HEADERS)
    event = SimpleNamespace(comment_id="c9", author="octryx-ai", thread_root="4711", inline=True)
    finding = run.context["pr_review"]["open_findings"][0]
    run_id = await start_explain(db, project_id, pr, event, "why is round() wrong here?", finding)
    explained = await db.get(WorkflowRun, run_id)
    await db.refresh(explained)
    assert (explained.workflow_key, explained.outcome) == ("pr-review-explain", "done")
    system, user = asked[0]
    assert '{"answer"' in system and "Question: why is round() wrong here?" in user
    assert "F1 totals.py:3 [high] Use half-away-from-zero rounding." in user and "+    return round(subtotal)" in user
    reply = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert reply["thread_answers"] == [{"comment_id": "4711", "resolve": False,
                                        "reply": "💡 **Octryx explains** · `round()` rounds half to even: 2.5 becomes 2."}]
    assert "commit_status" not in reply and "summary" not in reply  # read only: nothing else changes


async def test_explain_in_a_thread_starts_its_run_in_the_background_with_the_threads_finding(db, monkeypatch,
                                                                                            tmp_path):
    _project_id, record, _run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    _provider(monkeypatch, head, [_comment("c3", "octryx-ai", "@octryx explain why?", inline=True,
                                           in_reply_to="4711")])
    from app.services.pr_review_bot import bot_state, commands

    spawned = []
    monkeypatch.setattr(commands, "spawn", lambda coroutine: spawned.append(coroutine.cr_frame.f_locals) or
                        coroutine.close())
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"explain": 1}
    assert spawned[0]["question"] == "why?" and spawned[0]["finding"]["id"] == "F1"  # never blocks the poll


def test_explain_runs_on_the_reviews_seats_unless_a_route_is_named():
    from app.services.pr_review_bot.explain import _on_seats
    from app.services.workflow_runs.review.choice import ReviewChoice

    run_default = ReviewChoice(engine="claude_code", model="claude-haiku-5-5", route="company", model_source="platform",
                               route_source="run")
    assert _on_seats(run_default).route == "seat"
    named = ReviewChoice(engine="claude_code", model="claude-haiku-5-5", route="company", model_source="platform",
                         route_source="workspace")
    assert _on_seats(named).route == "company"  # the Workspace's route still decides
    foreign = ReviewChoice(engine="claude_code", model="gpt-5", route="company", model_source="node",
                           route_source="run")
    assert _on_seats(foreign).route == "company"  # a model outside the engine's family has no seat


async def test_the_explain_seat_is_the_commenters_not_the_authors(db):
    from app.services.pr_review_bot import seat_choice
    from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

    workspace = await seed_workspace(db)
    author = await seed_member(db, workspace_id=workspace, role="admin")
    asker = await seed_member(db, workspace_id=workspace, role="admin")
    db.add_all([UserLinkedAccount(user_id=author, platform="github", username="author"),
                UserLinkedAccount(user_id=asker, platform="github", username="asker")])
    await db.flush()
    facts = {"repository": "github:acme/pay", "pr_id": "2", "author": "author",
             "explain": {"author": "asker", "author_id": ""}}
    run = WorkflowRun(project_id=workspace, workflow_kind="phased", title="t", requested_by="bot",
                      workflow_key="pr-review-explain", repository="github:acme/pay", branch="f",
                      context={"pr_review": facts})
    assert seat_choice.is_bot_run(run)
    chosen = await seat_choice.bot_seat_person(db, run)
    assert (chosen.user.id, chosen.source) == (asker, "commenter")


def test_an_accepted_repository_rule_adds_to_the_central_rules_and_never_replaces_them():
    from app.services.code_style.brief import reviewer_checklist
    from app.services.code_style.resolve import effective, flat

    levels = {"installation": {"rules": "Every public function has a docstring."},
              "workspace": {"rules": "Money is a Decimal, never a float."},
              "repository": {"rules": "- Do not report in totals.py: rounding follows the bank.\n"
                                      "Money is a Decimal, never a float."}}
    general = flat(effective(levels, None))
    assert general["rules"] == ("Every public function has a docstring.\nMoney is a Decimal, never a float.\n"
                                "- Do not report in totals.py: rounding follows the bank.")  # each line once
    checklist = reviewer_checklist({"general": general, "languages": {}})
    assert "Money is a Decimal" in checklist and "rounding follows the bank" in checklist
    assert "Every public function has a docstring." in checklist
