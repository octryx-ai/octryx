"""A person's answer in a finding's thread shapes the next pass.

A reply like "coupons are applied by the checkout service, never in order_total" must not stay a correction only
while the next incremental pass repeats the finding word for word. The reply is remembered on the open finding, the
follow-up review gets it and may answer ``withdrawn`` (the thread is answered and resolved), unless it names new
evidence. And the bot's own thread replies never count as a person's (one login can serve the bot and the person)."""

from __future__ import annotations

import re

from app.services.pr_review_bot import bot_state, comment_poll
from app.services.pr_review_bot.incremental import Effective, effective, seed, thread_answers
from app.services.pr_review_bot.render import build_post
from app.services.workflow_runs.corrections.signature import data
from app.services.workflow_runs.review.convergence import Scope, follow_up_task, previous_findings, settle_follow_up
from tests.test_pr_review_bot_commands import _comment
from tests.test_pr_review_bot_explain_ignore import _provider, _reviewed

ANSWER = "In this shop coupons are applied by the checkout service, never inside order_total."


async def test_a_persons_reply_in_the_thread_is_kept_on_the_open_finding_once(db, monkeypatch, tmp_path):
    _project_id, record, run, head, owner, _tools = await _reviewed(db, monkeypatch, tmp_path)
    _provider(monkeypatch, head, [
        _comment("c1", "octryx-ai", ANSWER, inline=True, in_reply_to="4711"),
        _comment("c2", "octryx-ai", "✅ Fixed in `abc1234`. Rounds half away from zero now.", inline=True,
                 in_reply_to="4711"),  # the bot's own reply under the same login
        _comment("c3", "stranger", "This finding is wrong, trust me.", inline=True, in_reply_to="4711"),
        _comment("c4", "octryx-ai", "A general remark on the change.")])  # not in a finding's thread
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    await comment_poll.poll_comments(db, record, owner.id)
    await comment_poll.poll_comments(db, record, owner.id)  # the next poll sees c1 again: kept once
    await db.refresh(run)
    finding = run.context["pr_review"]["open_findings"][0]
    assert finding["replies"] == [ANSWER] and finding["reply_ids"] == ["c1"]
    assert seed(run.context["pr_review"])["findings"][0]["replies"] == [ANSWER]


def test_the_follow_up_gets_the_replies_and_may_withdraw_the_finding():
    previous = {"node_id": "independent_review", "verdict": "changes", "findings": [
        {"id": "F3", "severity": "low", "file": "shop/pricing.py", "line": 29, "fix": "Wire apply_coupon into "
         "order_total.", "replies": [ANSWER]},
        {"id": "F4", "severity": "medium", "file": "shop/pricing.py", "line": 35, "fix": "Add tests."}]}
    node = type("Node", (), {"id": "independent_review"})()
    findings = previous_findings(type("Run", (), {"context": {"review": previous}})(), node)
    assert '"replies": ["In this shop coupons' in follow_up_task(findings)
    settled = settle_follow_up({"summary": "s", "previous": [
        {"id": "F3", "status": "withdrawn", "evidence": "Coupons are applied by the checkout service."},
        {"id": "F4", "status": "not_fixed", "evidence": "No test file in the delta."}], "findings": []},
        findings, Scope(changed=("shop/pricing.py",)))
    record = settled.record()
    assert [item["id"] for item in record["findings"]] == ["F4"]
    assert [(item["id"], item["dropped"]) for item in record["dropped"]] == [("F3", "withdrawn")]


def test_a_withdrawn_finding_is_answered_and_resolved_in_its_thread_and_named_in_the_summary():
    before = {"open_findings": [
        {"id": "F3", "severity": "low", "file": "shop/pricing.py", "line": 29, "fix": "Wire it.", "comment_id": "3",
         "replies": [ANSWER]},
        {"id": "F4", "severity": "medium", "file": "shop/pricing.py", "line": 35, "fix": "Add tests.",
         "comment_id": "4"}]}
    record = {"verdict": "changes", "summary": "s", "findings": [before["open_findings"][1]],
              "dropped": [{**before["open_findings"][0], "dropped": "withdrawn"}],
              "follow_up": [{"id": "F3", "status": "withdrawn", "evidence": "The checkout applies coupons."},
                            {"id": "F4", "status": "not_fixed", "evidence": "No test in the delta."}]}
    passed = effective(record, before)
    assert isinstance(passed, Effective) and [item["id"] for item in passed.withdrawn] == ["F3"]
    assert passed.fixed == [] and passed.still_open == 1
    answers = {item["id"]: item for item in thread_answers(passed, "af9aaca0")}
    assert answers["F3"]["resolve"] is True and answers["F3"]["comment_id"] == "3"
    assert answers["F3"]["reply"].startswith("↩️ Withdrawn after the answer in this thread.")
    assert answers["F4"]["reply"].startswith("Still open after `af9aaca`.")
    post = build_post(passed.review, {}, provider="gitlab", facts={"sha": "af9aaca0", "incremental": {
        "from": "e611384", "fixed": [], "withdrawn": passed.withdrawn, "still_open": 1, "new": 0}})
    assert "0 fixed, 1 withdrawn, 1 still open, 0 new." in post.summary
    assert "Withdrawn after an answer in the thread:" in post.summary


def test_every_reply_the_bot_writes_is_recognised_as_the_bots_own():
    patterns = data()["pr_comment"]["bot_bodies"]
    replies = ["✅ Fixed in `af9aaca`. shop/pricing.py:34", "Still open after `af9aaca`. The diff only touches it.",
               "◐ Partly fixed in `af9aaca`. It rounds now. Still open: Add tests.",
               "↩️ Withdrawn after the answer in this thread. The checkout applies coupons.",
               "🙈 Ignored by @root: checkout applies them. Proposed to the Workspace admins as a team rule.",
               "💡 **Octryx explains** · Returning the amount unchanged is allowed by the finding, but I'd pick the ValueError option.",
               "🔧 Octryx pushed `abc1234` to the pull request.", "⏸️ Octryx paused its reviews on this pull request.",
               "Octryx: only people with an Octryx account in this Workspace can use it."]
    assert [reply for reply in replies if not any(re.match(pattern, reply) for pattern in patterns)] == []
    assert not any(re.match(pattern, ANSWER) for pattern in patterns)
    assert not any(re.match(pattern, "💡 Idea: apply coupons in checkout") for pattern in patterns)  # a person's


async def test_without_a_previous_post_nothing_is_kept(db):
    from app.services.pr_review_bot.comment_events import CommentEvent
    from app.services.pr_review_bot.finding_replies import remember

    event = CommentEvent("github:a/b", "1", "c9", "someone", ANSWER, in_reply_to="1", inline=True)
    assert await remember(db, "no-workspace", event) is False
