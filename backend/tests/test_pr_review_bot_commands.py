"""PR review bot: ``@octryx`` commands.

- a comment whose line starts with ``@octryx`` is a command, from a webhook of any platform or from the sync's poll
  (a local installation gets no webhook); the first poll only sets the cursor;
- only a Workspace member with a linked account and write access may (GitHub: the collaborator permission; where
  the platform does not tell, a Workspace admin); anybody else gets one answer and nothing runs;
- ``pause`` stops the webhook and the sync for that pull request until ``resume``; ``review full`` reviews the current
  head again, in full; a comment is acted on once; every command is answered in the pull request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import UserLinkedAccount, WorkflowRun
from app.services.pr_review_bot import bot_state, comment_poll
from app.services.pr_review_bot import sync as bot_sync
from app.services.pr_review_bot.commands import HELP, PAUSE, REVIEW_FULL, parse_command
from app.services.pr_review_bot.comment_events import comment_event, listed_comment
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.starter import admit
from app.tools.bitbucket_impl import _bitbucket_pr_comments as bb_comments
from app.tools.connectors import github_pr_comments
from tests.knowledge_evidence_seed_support import seed_member
from tests.pr_review_bot_flow_support import FIXTURES, HEADERS, _payload, _workspace


def test_a_command_is_the_first_line_that_starts_with_the_mention():
    command = parse_command("Thanks!\n@octryx review full please")
    assert (command.name, command.args) == (REVIEW_FULL, "please")
    assert parse_command("> @Octryx PAUSE").name == PAUSE  # quoted and in capitals
    assert parse_command("@octryx dance").name == HELP
    assert parse_command("ask @octryx review full later") is None  # not at the start of a line: a mention, no command
    assert parse_command("Octryx paused its reviews. Resume them with `resume` after the mention.") is None


def test_the_comment_events_of_every_platform_read_alike():
    github = comment_event({"action": "created", "issue": {"number": 2, "pull_request": {}},
                            "comment": {"id": 9, "user": {"login": "octryx-ai"}, "body": "@octryx pause"},
                            "repository": {"full_name": "octryx-ai/review-bot-test"}},
                           {"X-GitHub-Event": "issue_comment"})
    assert (github.repository, github.pr_id, github.comment_id, github.author, github.inline) == (
        "github:octryx-ai/review-bot-test", "2", "9", "octryx-ai", False)
    thread = comment_event({"action": "created", "pull_request": {"number": 2}, "repository": {"full_name": "a/b"},
                            "comment": {"id": 11, "in_reply_to_id": 7, "user": {"login": "x"}, "body": "@octryx"}},
                           {"X-GitHub-Event": "pull_request_review_comment"})
    assert (thread.inline, thread.thread_root) == (True, "7")
    assert comment_event({"action": "edited", "issue": {"number": 2, "pull_request": {}}, "comment": {"id": 9}},
                         {"X-GitHub-Event": "issue_comment"}) is None
    assert comment_event({"action": "created", "issue": {"number": 3}, "comment": {"id": 1, "body": "x"},
                          "repository": {"full_name": "a/b"}}, {"X-GitHub-Event": "issue_comment"}) is None  # an issue
    cloud = comment_event({"repository": {"full_name": "acme/pay"}, "pullrequest": {"id": 7}, "comment": {
        "id": 40, "content": {"raw": "@octryx resume"}, "user": {"account_id": "557058:anna", "nickname": "anna"},
        "parent": {"id": 39}, "inline": {"path": "x"}}}, {"X-Event-Key": "pullrequest:comment_created"})
    assert (cloud.author_id, cloud.in_reply_to, cloud.inline) == ("557058:anna", "39", True)
    server = comment_event({"eventKey": "pr:comment:added", "pullRequest": {"id": 12, "toRef": {"repository": {
        "slug": "demo-shop", "project": {"key": "P"}}}}, "comment": {"id": 5, "text": "@octryx pause",
                                                                 "author": {"name": "alice"}}}, {})
    assert (server.repository, server.author, server.author_id) == ("bitbucket:P/demo-shop", "alice", "")
    listed = listed_comment("github:a/b", {"id": "1", "pr": "2", "author": "x", "author_id": "77", "body": "b"})
    assert (listed.author_id, listed.pr_id) == ("", "2")  # GitHub links people by login, never by numeric id


async def test_github_lists_comments_on_open_pull_requests_and_reads_permissions():
    calls = []

    async def http(method, url, *, headers=None, params=None, **_):
        calls.append((url, params))
        if url.endswith("/issues/comments"):
            return [{"id": 1, "issue_url": "https://x/issues/2", "user": {"login": "a"}, "body": "@octryx pause",
                     "created_at": "2026-11-17T20:01:00Z"},
                    {"id": 2, "issue_url": "https://x/issues/99", "user": {"login": "a"}, "body": "an issue"}]
        if url.endswith("/pulls/comments"):
            return [{"id": 3, "pull_request_url": "https://x/pulls/2", "in_reply_to_id": 8, "user": {"login": "b"},
                     "body": "@octryx review full", "created_at": "2026-11-17T20:00:00Z"}]
        if url.endswith("/collaborators/a/permission"):
            return {"permission": "write"}
        import httpx

        raise httpx.HTTPStatusError("403", request=httpx.Request("GET", url), response=httpx.Response(403))

    found = await github_pr_comments.comments_since(http, {}, "https://api/repos/a/b", "2026-11-17T19:55:00Z",
                                                    {"2"})
    assert [(item["id"], item["inline"], item["in_reply_to"]) for item in found] == [("3", True, "8"),
                                                                                     ("1", False, "")]
    assert calls[0][1]["since"] == "2026-11-17T19:55:00Z"
    assert await github_pr_comments.permissions(http, {}, "https://api/repos/a/b", ["a", "c"]) == {
        "a": "write", "c": "unknown"}


async def test_bitbucket_cloud_and_server_list_the_comments_since(monkeypatch):
    async def cloud(_context, method, path, *, params=None, payload=None):
        assert params["q"] == 'created_on>"2026-11-17T20:00:00+00:00"'
        return {"values": [{"id": 40, "content": {"raw": "@octryx pause"}, "user": {"account_id": "557058:a"},
                            "created_on": "2026-11-17T20:05:00+00:00"}, {"id": 41, "deleted": True}]}

    monkeypatch.setattr(bb_comments, "cloud_request", cloud)
    found = await bb_comments.cloud_comments(None, "acme", "pay", ["7"], "2026-11-17T20:00:00+00:00")
    assert [(item["id"], item["author_id"], item["pr"]) for item in found] == [("40", "557058:a", "7")]
    after = int(datetime(2026, 11, 17, 20, tzinfo=UTC).timestamp() * 1000)

    async def pages(path, _params):
        return [{"action": "COMMENTED", "comment": {"id": 5, "text": "old", "createdDate": after - 1, "comments": [
            {"id": 6, "text": "@octryx review full", "createdDate": after + 1, "author": {"name": "alice"}}]}}]

    found = await bb_comments.server_comments(pages, "/rest/api/1.0/projects/P/repos/r", ["12"],
                                              "2026-11-17T20:00:00+00:00")
    assert [(item["id"], item["in_reply_to"], item["author"]) for item in found] == [("6", "5", "alice")]


@pytest.fixture
def provider(monkeypatch):
    """The governed list and post tools, scripted: the open pull request #42 and the comments since the cursor."""
    head = json_head()
    state = {"comments": [], "permissions": {"octryx-ai": "write", "anna": "read"}, "posts": [], "lists": [],
             "head": head}

    async def tools(tool, arguments, context):
        if tool == "list_github_pull_request_heads":
            state["lists"].append(arguments)
            answer = {"pull_requests": [state["head"]]}
            if "comments_since" in arguments:
                answer["comments"] = list(state["comments"])
            if "permissions_for" in arguments:
                answer["permissions"] = {login: state["permissions"].get(login.lower(), "none")  # GitHub ignores case
                                         for login in arguments["permissions_for"]}
            return answer
        state["posts"].append((tool, arguments, context.run_capability))
        return {"status": "posted"}

    monkeypatch.setattr("app.tools.registry.execute_tool_with_plugins", tools)
    return state


def json_head() -> dict:
    import json

    from app.tools.connectors.github_pr_review import _head

    return _head(json.loads((FIXTURES / "github_pulls_page.json").read_text())[0])


def _comment(ident: str, author: str, body: str, **more) -> dict:
    return {"id": ident, "pr": "42", "author": author, "author_id": "1", "body": body,
            "created_at": "2026-11-17T20:00:00Z", "in_reply_to": "", "inline": False, **more}


async def test_commands_from_the_poll_pause_resume_and_review_again_and_strangers_are_refused(
        db, monkeypatch, provider):
    project_id, record, _hook = await _workspace(db, trigger="sync")
    from tests.phased_workflow_fixtures import admin_user

    owner = await admin_user(db)
    member = await seed_member(db, workspace_id=project_id, role="member")
    db.add_all([UserLinkedAccount(user_id=owner.id, platform="github", username="Octryx-AI"),
                UserLinkedAccount(user_id=member, platform="github", username="anna")])
    await db.flush()
    started = []

    async def start(db_, *, user, workflow_key, project_id, repository, branch, session, context, automatic):
        run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key=workflow_key, title="bot",
                          requested_by=user.id, repository=repository, branch=branch, context=context)
        db_.add(run)
        await db_.flush()
        started.append(context["pr_review"])
        return run

    monkeypatch.setattr("app.services.workflow_runs.records.start_run", start)
    provider["comments"] = [_comment("c1", "octryx-ai", "@octryx pause")]
    assert await bot_sync.sync_repository(db, record, start=start) == {"started": 1}  # first: the cursor only
    assert bot_state.cursor(record) and not bot_state.is_paused(record, "42")

    assert (await bot_sync.sync_repository(db, record, start=start))["command_pause"] == 1
    assert bot_state.is_paused(record, "42") and "comments_since" in provider["lists"][-2]
    tool, reply, capability = provider["posts"][-1]
    assert tool == "post_github_pull_request_review" and reply["comment"].startswith("⏸️ Octryx paused")
    assert reply["pr_number"] == "42" and capability["class"] == "deliver"
    event = pull_request_event(_payload("f" * 40, number=42), HEADERS)
    assert (await admit(db, project_id, event, trigger="sync")).reason == "paused"

    provider["comments"] = [_comment("c1", "octryx-ai", "@octryx pause"),  # seen: never again
                            _comment("c2", "anna", "@octryx resume"),  # read access only
                            _comment("c3", "stranger", "@octryx resume"),  # no linked account
                            _comment("c4", "octryx-ai", "@octryx review full", inline=True, in_reply_to="900")]
    counted = await comment_poll.poll_comments(db, record, owner.id)
    assert counted == {"seen": 1, "refused": 2, "review full": 1}
    replies = [arguments for _tool, arguments, _cap in provider["posts"][-3:]]
    assert "write access" in replies[0]["comment"] and "Octryx account" in replies[1]["comment"]
    assert replies[2]["thread_answers"][0]["comment_id"] == "900"  # answered in the thread it was written in
    assert "started a full review" in replies[2]["thread_answers"][0]["reply"]
    assert started[-1]["force_full"] is True and started[-1]["requested_by"] == owner.id  # also while paused

    # A push while paused, then ``resume``: the same sync acts on the command first and reviews the new head
    # (it does not wait for the next sync).
    provider["head"] = {**provider["head"], "head_sha": "e" * 40}
    assert (await bot_sync.sync_repository(db, record, start=start)).get("skipped") == 1  # paused
    provider["comments"] = [_comment("c5", "Octryx-AI", "@octryx resume")]
    counted = await bot_sync.sync_repository(db, record, start=start)
    assert not bot_state.is_paused(record, "42")
    assert (counted["command_resume"], counted["started"]) == (1, 1) and started[-1]["head_sha"] == "e" * 40


async def test_the_first_poll_never_acts_on_older_comments_and_the_cursor_overlaps(db, provider):
    _project_id, record, _hook = await _workspace(db, trigger="sync")
    provider["comments"] = [_comment("old", "octryx-ai", "@octryx pause")]
    assert await comment_poll.poll_comments(db, record, "bot") == {}
    assert provider["posts"] == [] and provider["lists"] == []
    cursor = datetime.fromisoformat(bot_state.cursor(record))
    await comment_poll.poll_comments(db, record, "bot")
    since = datetime.fromisoformat(provider["lists"][-1]["comments_since"])
    assert cursor - since == timedelta(minutes=5)


async def test_a_webhook_comment_with_a_command_is_acted_on_in_the_background(db, monkeypatch):
    from app.services.pr_review_bot import webhook as bot_webhook

    _project_id, _record, hook = await _workspace(db)
    spawned = []
    monkeypatch.setattr(bot_webhook, "_spawn", lambda coroutine: spawned.append(coroutine) or coroutine.close())
    payload = {"action": "created", "issue": {"number": 42, "pull_request": {}},
               "repository": {"full_name": "acme/pay"},
               "comment": {"id": 9, "user": {"login": "octryx-ai"}, "body": "@octryx review full"}}
    headers = {"X-GitHub-Event": "issue_comment"}
    assert await bot_webhook.on_scm_webhook(db, hook, payload, headers, is_test=False) == {
        "outcome": "queued", "reason": "command"}
    plain = {**payload, "comment": {**payload["comment"], "body": "Looks good to me"}}
    assert await bot_webhook.on_scm_webhook(db, hook, plain, headers, is_test=False) is None
    # A person's comment without a command is no command, but a correction kept for its Workspace, in its own
    # background session.
    assert [coroutine.cr_code.co_name for coroutine in spawned] == ["on_comment", "on_person_comment"]


async def test_github_also_reads_review_summaries_and_pull_requests_closed_within_a_day():
    """"Request changes" with a text is a person's correction, and the e2e harness closes its pull requests
    within minutes, so a comment written just before still counts."""
    async def http(method, url, *, headers=None, params=None, **_):
        if url.endswith("/pulls") and params["state"] == "closed":
            return [{"number": 7, "closed_at": "2026-11-20T08:00:00Z", "updated_at": "2026-11-20T08:00:00Z"},
                    {"number": 6, "closed_at": "2026-11-18T08:00:00Z", "updated_at": "2026-11-18T08:00:00Z"}]
        if url.endswith("/pulls/7/reviews"):
            return [{"id": 51, "user": {"login": "a"}, "body": "Use the cents helper here.",
                     "state": "CHANGES_REQUESTED", "submitted_at": "2026-11-20T07:59:00Z"},
                    {"id": 52, "user": {"login": "a"}, "body": "", "state": "APPROVED",
                     "submitted_at": "2026-11-20T07:59:30Z"},  # no text: nothing to learn
                    {"id": 53, "user": {"login": "a"}, "body": "draft", "state": "PENDING", "submitted_at": None},
                    {"id": 50, "user": {"login": "a"}, "body": "old", "state": "COMMENTED",
                     "submitted_at": "2026-11-19T07:00:00Z"}]  # before the cursor
        return []

    now = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    closed = await github_pr_comments.recently_closed(http, {}, "https://api/repos/a/b", now=now)
    assert [pr["number"] for pr in closed] == [7]  # #6 closed two days ago
    assert github_pr_comments.updated_since(closed, "2026-11-20T07:00:00Z") == {"7"}
    found = await github_pr_comments.comments_since(http, {}, "https://api/repos/a/b", "2026-11-20T07:00:00Z",
                                                    {"7"}, reviewed={"7"})
    assert [(item["id"], item["pr"], item["body"], item["review"]) for item in found] == [
        ("review-51", "7", "Use the cents helper here.", True)]


async def test_a_command_on_a_closed_pull_request_or_in_a_review_summary_is_only_a_correction(
        db, monkeypatch, provider):
    project_id, record, _hook = await _workspace(db, trigger="sync")
    people = []

    async def corrections(db_, project_id_, events):
        people.extend(event.comment_id for event in events)

    monkeypatch.setattr(comment_poll, "_people_comments", corrections)
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    provider["comments"] = [_comment("c9", "octryx-ai", "@octryx pause", pr="77"),  # #77 is closed: not listed open
                            _comment("review-5", "octryx-ai", "@octryx pause"),
                            _comment("c10", "octryx-ai", "Please keep the totals in cents.")]
    assert await comment_poll.poll_comments(db, record, "bot") == {}
    assert people == ["c9", "review-5", "c10"] and provider["posts"] == [] and not bot_state.is_paused(record, "42")
