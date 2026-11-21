"""PR review bot on GitLab, through the same flow as GitHub and Bitbucket (merge requests, API v4).

- a ``Merge Request Hook`` that opens, reopens, pushes to or readies a merge request is one event (draft and fork
  named); any other action is none; a ``Note Hook`` on a merge request is a comment whose thread is its discussion;
- a pushed merge request is checked out read-only, marked ``pending``, reviewed and answered on GitLab: the summary,
  the inline comment with GitLab's one-click ``suggestion:-N+0`` block, the CI read for the reviewed commit and the
  status, all through the GitLab tools with the merge request's ``mr_iid``;
- the hourly sync starts only the ready heads of a project (a draft and a fork wait);
- ``@octryx`` commands from the poll: the commenter's GitLab access decides, the answer mentions ``@username``, and
  a command in a diff discussion is answered in that discussion.
"""

from __future__ import annotations

import json

import pytest

from app.models import UserLinkedAccount, WorkflowRun
from app.models.integration.webhook import Webhook
from app.models.runtime.code_intelligence import CodeRepository
from app.services.pr_review_bot import actions as bot_actions
from app.services.pr_review_bot import bot_state, ci_results, comment_poll
from app.services.pr_review_bot import sync as bot_sync
from app.services.pr_review_bot import webhook as bot_webhook
from app.services.pr_review_bot.comment_events import comment_event
from app.services.pr_review_bot.diff_lines import CONTEXT, old_line_of, parse_diff
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.settings import BotSettings, repository_of, store_settings
from app.services.pr_review_bot.starter import TRIGGER_WEBHOOK, start_review
from app.services.workflow_runs.platform import scm
from app.services.workflow_runs.review.runner import run_due_reviews
from app.tools.connectors.gitlab_mr_review import _head
from tests.agent_definition_revision_fixtures import make_project
from tests.knowledge_evidence_seed_support import seed_member
from tests.phased_workflow_fixtures import admin_user
from tests.pr_review_bot_flow_support import FIXTURES, REVIEW, _origin
from tests.test_workflow_run_platform_actions import FakeTools
from tests.workflow_run_review_support import ScriptedReviewer

HOOK = {"X-Gitlab-Event": "Merge Request Hook", "X-Gitlab-Token": "fake-test-token"}
NOTE_HOOK = {"X-Gitlab-Event": "Note Hook"}
THREAD = "6a9c1750b37d513a43987b574953fceb50b03ce7"
SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
MR_URL = "https://gitlab.example.test/acme/pay/-/merge_requests/42"


def _hook(head: str = SHA, **changes) -> dict:
    payload = json.loads((FIXTURES / "gitlab_merge_request_hook.json").read_text())
    payload["object_attributes"]["last_commit"]["id"] = head
    payload["object_attributes"].update(changes)
    return payload


async def _workspace(db, trigger: str = "both") -> tuple[str, CodeRepository, Webhook]:
    project = await make_project(db)
    owner = await admin_user(db)
    record = CodeRepository(project_id=project.id, name="acme/pay", provider="gitlab", repo_root="/tmp/none",
                            config_json={})
    # The review as a required check (``gate``): these flows assert the failing status; ``inform`` is the default.
    store_settings(record, BotSettings(trigger, status_policy="gate"))
    hook = Webhook(name="MRs", project_id=project.id, owner_id=owner.id, source_type="scm_pull_request",
                   is_active=True)
    db.add_all([record, hook])
    await db.flush()
    return project.id, record, hook


def test_merge_request_hooks_and_note_hooks_read_like_every_other_platform():
    pushed = pull_request_event(_hook(), HOOK)
    assert (pushed.repository, pushed.pr_id, pushed.head_sha, pushed.source_branch, pushed.target_branch) == (
        "gitlab:acme/pay", "42", SHA, "feature/PAY-1-totals", "main")
    assert (pushed.author, pushed.url, pushed.draft, pushed.fork) == ("dev-anna", MR_URL, False, False)
    assert pull_request_event(_hook(action="open", oldrev=None), HOOK).pr_id == "42"
    assert pull_request_event(_hook(source_project_id=99), HOOK).fork is True
    assert pull_request_event(_hook(draft=True), HOOK).draft is True
    # An update without new commits (a title, a label, an approval) and a close start nothing ...
    assert pull_request_event(_hook(oldrev=None), HOOK) is None
    assert pull_request_event(_hook(action="close"), HOOK) is None
    assert pull_request_event(_hook(), {"X-Gitlab-Event": "Push Hook"}) is None
    # ... a draft made ready does.
    ready = _hook(oldrev=None)
    ready["changes"]["draft"] = {"previous": True, "current": False}
    assert pull_request_event(ready, HOOK).pr_id == "42"

    note = json.loads((FIXTURES / "gitlab_note_hook.json").read_text())
    event = comment_event(note, NOTE_HOOK)
    assert (event.repository, event.pr_id, event.comment_id, event.author, event.body) == (
        "gitlab:acme/pay", "42", "501", "dev-anna", "@octryx explain why")
    assert (event.inline, event.thread_root) == (True, THREAD)  # answered in its discussion
    overview = json.loads(json.dumps(note))
    overview["object_attributes"].update(type=None, position=None)
    assert (comment_event(overview, NOTE_HOOK).inline, comment_event(overview, NOTE_HOOK).thread_root) == (
        False, "501")
    for change in ({"system": True}, {"action": "update"}, {"noteable_type": "Issue"}):
        edited = json.loads(json.dumps(note))
        edited["object_attributes"].update(change)
        assert comment_event(edited, NOTE_HOOK) is None


def test_gitlab_suggestions_name_the_lines_they_replace_and_context_lines_keep_their_old_number():
    diff = ("diff --git a/totals.py b/totals.py\n--- a/totals.py\n+++ b/totals.py\n@@ -10,4 +10,5 @@\n"
            " def total(items):\n+    items = list(items)\n     subtotal = sum(items)\n-    return int(subtotal)\n"
            "+    return round(subtotal)\n")
    files = parse_diff(diff)
    assert (old_line_of(files, "totals.py", 12), old_line_of(files, "totals.py", 11)) == (11, 0)
    review = {"verdict": "changes", "findings": [
        {"severity": "high", "file": "totals.py", "line": 13, "start_line": 11, "fix": "Round half up.",
         "suggestion": "    items = list(items)\n    subtotal = sum(items)\n    return int(subtotal + 0.5)"},
        {"severity": "low", "file": "totals.py", "line": 12, "fix": "Name it."}]}
    post = build_post(review, files, provider="gitlab", facts={"sha": SHA})
    ranged, context = post.comments
    assert "```suggestion:-2+0\n    items = list(items)" in ranged.body and ranged.to_dict()["start_line"] == 11
    assert (context.line_type, context.to_dict()["old_line"]) == (CONTEXT, 11)
    github = build_post(review, files, provider="github", facts={"sha": SHA})
    assert "old_line" not in github.comments[1].to_dict()  # only GitLab anchors on both sides


async def test_a_pushed_merge_request_is_reviewed_and_answered_on_gitlab(db, monkeypatch, tmp_path):
    clone, head = _origin(tmp_path)
    tools = FakeTools(monkeypatch, {
        "prepare_gitlab_repository": [{"local_path": str(clone)}],
        "post_gitlab_merge_request_review": [{"status": "posted"}],
        "get_gitlab_commit_checks": [{"checks": [{"name": "test", "state": "failure",
                                                  "url": "https://gitlab.example.test/jobs/1"}]}]})
    monkeypatch.setattr(bot_actions, "dispatch_tool", scm.dispatch_tool)
    monkeypatch.setattr(ci_results, "dispatch_tool", scm.dispatch_tool)
    project_id, record, hook = await _workspace(db)
    assert repository_of(record) == "gitlab:acme/pay"
    monkeypatch.setattr(bot_webhook, "_spawn", lambda coroutine: coroutine.close())
    assert await bot_webhook.on_scm_webhook(db, hook, _hook(head), HOOK, is_test=False) == {"outcome": "queued"}
    assert (await bot_webhook.on_scm_webhook(db, hook, _hook(head, draft=True), HOOK, is_test=False))[
        "reason"] == "draft"

    started = await start_review(db, project_id, pull_request_event(_hook(head), HOOK), trigger=TRIGGER_WEBHOOK)
    run = await db.get(WorkflowRun, started.run_id)
    assert (run.repository, run.branch, run.pull_request["id"]) == ("gitlab:acme/pay", "feature/PAY-1-totals", "42")
    prepare = next(call[1] for call in tools.calls if call[0] == "prepare_gitlab_repository")
    assert (prepare["project"], prepare["review_only"]) == ("acme/pay", True)
    posts = [call[1] for call in tools.calls if call[0] == "post_gitlab_merge_request_review"]
    assert posts == [{"project": "acme/pay", "mr_iid": "42", "commit": head, "commit_status": {
        "state": "pending", "description": "Octryx is reviewing", "context": "octryx/review", "target_url": MR_URL}}]

    assert await run_due_reviews(db, model_factory=ScriptedReviewer(REVIEW).factory) == 1
    await db.refresh(run)
    assert (run.status, run.outcome) == ("completed", "done")
    ci = next(call[1] for call in tools.calls if call[0] == "get_gitlab_commit_checks")
    assert ci == {"project": "acme/pay", "commit": head}
    posted = [call[1] for call in tools.calls if call[0] == "post_gitlab_merge_request_review"][-1]
    assert (posted["mr_iid"], posted["commit_status"]["state"]) == ("42", "failure")
    assert posted["comments"] == [{"path": "totals.py", "line": 3, "line_type": "ADDED", "body": (
        "**🔴 High** · F1\n\nUse half-away-from-zero rounding.\n\n```suggestion:-0+0\n"
        "    return int(subtotal + 0.5)\n```")}]
    assert "**Blocking (CI):** 1 check(s) failed" in posted["summary"]
    assert "'test' failed on this commit. https://gitlab.example.test/jobs/1" in posted["summary"]


async def test_the_hourly_sync_starts_only_the_ready_heads_of_a_project(db, monkeypatch):
    project_id, record, _hook = await _workspace(db, trigger="sync")
    page = json.loads((FIXTURES / "gitlab_merge_requests_page.json").read_text())

    async def listed(tool, arguments, context):
        assert (tool, arguments["project"], context.project_ids) == (
            "list_gitlab_merge_request_heads", "acme/pay", [project_id])
        return {"pull_requests": [_head("acme/pay", mr) for mr in page]}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", listed)
    started = []

    async def start(db_, *, user, workflow_key, project_id, repository, branch, session, context, automatic):
        run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key=workflow_key, title="bot",
                          requested_by=user.id, repository=repository, branch=branch, context=context)
        db_.add(run)
        await db_.flush()
        started.append((repository, branch, context["pr_review"]["author"]))
        return run

    assert await bot_sync.sync_repository(db, record, start=start) == {"started": 1, "skipped": 2}
    assert started == [("gitlab:acme/pay", "feature/PAY-1-totals", "dev-anna")]  # the draft and the fork wait


@pytest.fixture
def gitlab_tools(monkeypatch):
    state = {"comments": [], "posts": [], "lists": [],
             "head": _head("acme/pay", json.loads((FIXTURES / "gitlab_merge_requests_page.json").read_text())[0])}

    async def tools(tool, arguments, context):
        if tool == "list_gitlab_merge_request_heads":
            state["lists"].append(arguments)
            answer = {"pull_requests": [state["head"]]}
            if "comments_since" in arguments:
                answer["comments"] = list(state["comments"])
            if "permissions_for" in arguments:
                levels = {"dev-anna": "maintain", "dev-ben": "read"}
                answer["permissions"] = {name: levels.get(name, "none") for name in arguments["permissions_for"]}
            return answer
        state["posts"].append((tool, arguments))
        return {"status": "posted"}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", tools)
    return state


async def test_commands_on_gitlab_read_the_members_access_mention_and_answer_in_the_discussion(db, gitlab_tools):
    project_id, record, _hook = await _workspace(db, trigger="sync")
    owner = await admin_user(db)
    member = await seed_member(db, workspace_id=project_id, role="member")
    db.add_all([UserLinkedAccount(user_id=owner.id, platform="gitlab", username="dev-anna"),
                UserLinkedAccount(user_id=member, platform="gitlab", username="dev-ben")])
    await db.flush()
    assert await comment_poll.poll_comments(db, record, owner.id) == {}  # the first poll sets the cursor only

    def note(ident, author, body, **more):
        return {"id": ident, "pr": "42", "author": author, "author_id": "", "body": body,
                "created_at": "2026-11-20T09:10:00+00:00", "in_reply_to": "", "inline": False, **more}

    gitlab_tools["comments"] = [note("301", "dev-anna", "@octryx pause"),
                                note("402", "dev-ben", "@octryx resume", in_reply_to=THREAD, inline=True)]
    assert await comment_poll.poll_comments(db, record, owner.id) == {"pause": 1, "refused": 1}
    assert bot_state.is_paused(record, "42")
    asked = [arguments["permissions_for"] for arguments in gitlab_tools["lists"] if "permissions_for" in arguments]
    assert asked == [["dev-anna"], ["dev-ben"]]  # GitLab tells the access level: it decides, not the Octryx role
    (tool, paused), (_tool, refused) = gitlab_tools["posts"]
    assert (tool, paused["project"], paused["mr_iid"], paused["commit"]) == (
        "post_gitlab_merge_request_review", "acme/pay", "42", SHA)
    assert paused["comment"].startswith("⏸️ Octryx paused") and "(by @dev-anna)" in paused["comment"]
    assert refused["thread_answers"][0]["comment_id"] == THREAD  # answered in the discussion it was written in
    assert "write access" in refused["thread_answers"][0]["reply"]
