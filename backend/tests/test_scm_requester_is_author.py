"""The requester as the pull request's author on every SCM: no self-review, a mention instead, and the run,
run card and Inbox say so."""

from __future__ import annotations

import pytest

import app.services.secure_work.coding.coding_pr_delivery as pr_delivery
import app.tools.bitbucket_impl._bitbucket_pull_requests as bitbucket_prs
import app.tools.connectors.github_pull_requests as github_prs
import app.tools.connectors.gitlab_merge_requests as gitlab_mrs
from app.models import UserLinkedAccount, WorkflowRunEvent
from app.services.ai_marking import MARKER_PREFIX, MarkingFacts, marker_line
from app.services.ai_marking_tools import mark_fields
from app.services.workflow_runs.attention import inbox_items
from app.services.workflow_runs.run_notices import reviewer_notice
from app.tools.context import ToolContext
from app.tools.scm_requester_rule import REQUESTER_IS_AUTHOR, apply_requester_rule
from tests.phased_workflow_fixtures import admin_user
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.test_workflow_run_platform_actions import FakeTools, _item, _repository, _run

pytestmark = pytest.mark.usefixtures("scripted_pool")

CONTEXT_CONFIG = {"github_url": "https://scm.test/api/v3", "gitlab_url": "https://gl.test",
                  "bitbucket_url": "https://bb.test", "bitbucket_username": "Admin-SCM", "bitbucket_token": "t"}


def test_the_rule_mentions_the_requester_only_when_they_are_the_author():
    kept, text, skipped = apply_requester_rule(["dev", "lead"], requester="dev", author="DEV", description="PAY-1",
                                               mention="@dev")
    assert (kept, skipped) == (["lead"], REQUESTER_IS_AUTHOR) and text.startswith("PAY-1\n\nRequested by @dev")
    assert apply_requester_rule(["dev", "lead"], requester="dev", author="bot", description="d", mention="@dev") == (
        ["dev", "lead"], "d", "")
    assert apply_requester_rule(["dev"], requester="dev", author="DEV", description="d", mention="@dev",
                                exact=True)[2] == ""  # Bitbucket Cloud account ids compare exactly


@pytest.mark.parametrize("author", ["admin-scm", "bot"])
async def test_github_gitlab_and_bitbucket_server_skip_the_requester_who_is_the_author(monkeypatch, author):
    await _requester_case(monkeypatch, author)


# The registry marks the arguments before the tool adds the mention, so the line follows the agent's own text.
async def test_new_pull_requests_carry_the_ai_marker_once_before_the_requester_mention(monkeypatch):
    facts = MarkingFacts(responsible="Run Owner", model="claude-haiku-5-5")
    created = await _requester_case(monkeypatch, "admin-scm", facts=facts)
    for text in created.values():
        assert text.startswith(f"PAY-1\n\n{marker_line(facts)}")
        assert text.count(MARKER_PREFIX) == 1
        assert text.index(MARKER_PREFIX) < text.index("Requested by @admin-scm")


async def _requester_case(monkeypatch, author: str, *, facts: MarkingFacts | None = None) -> dict[str, str]:
    sent: dict[str, list] = {"github": [], "gitlab": [], "bitbucket": []}

    async def github_http(method, url, **kwargs):
        sent["github"].append((url, kwargs.get("json_body") or {}))
        if url.endswith("/user"):
            return {"login": author}
        if url.endswith("/requested_reviewers"):
            return {"requested_reviewers": [{"login": name} for name in kwargs["json_body"]["reviewers"]]}
        return {"number": 9, "html_url": "https://scm.test/pr/9"}

    async def gitlab_http(method, url, **kwargs):
        sent["gitlab"].append((url, kwargs.get("json_body") or kwargs.get("params") or {}))
        if url.endswith("/user"):
            return {"username": author}
        if url.endswith("/users"):
            return [{"id": 41 if kwargs["params"]["username"] == "admin-scm" else 42}]
        return {"iid": 2, "web_url": "https://gl.test/mr/2"}

    async def bitbucket_post(context, path, *, payload):
        sent["bitbucket"].append((path, payload))
        return {"id": 3, "title": payload["title"]}, 201

    async def none(*_args, **_kwargs):
        return None

    async def headers(_context):
        return {}

    async def contract(db, **kwargs):
        return {"reviewers": list(kwargs["explicit_reviewers"]), "source": "explicit"}

    for module, http in ((github_prs, github_http), (gitlab_mrs, gitlab_http)):
        monkeypatch.setattr(module, "_http_json", http)
    monkeypatch.setattr(github_prs, "require_github_repository_operation", none)
    monkeypatch.setattr(github_prs, "_github_headers", headers)
    monkeypatch.setattr(gitlab_mrs, "require_gitlab_repository_operation", none)
    monkeypatch.setattr(gitlab_mrs, "_gitlab_headers", headers)
    monkeypatch.setattr(bitbucket_prs, "require_project_repository_operation", none)
    monkeypatch.setattr(bitbucket_prs, "_is_repo_allowed", lambda *_args: True)
    monkeypatch.setattr(bitbucket_prs, "_find_open_pull_request_for_branch", none)
    monkeypatch.setattr(bitbucket_prs, "_bitbucket_json_post", bitbucket_post)
    monkeypatch.setattr(pr_delivery, "reviewer_contract_for_bitbucket_pr_tool", contract)
    bot = author == "bot"
    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="s",
                          project_config={**CONTEXT_CONFIG, **({"bitbucket_username": "bot"} if bot else {})})
    args = {"title": "t", "from_branch": "b", "to_branch": "main", "reviewers": ["admin-scm", "lead"],
            "requester": "admin-scm", "description": "PAY-1"}

    github = await github_prs.CreateGitHubPullRequestTool().execute(
        mark_fields("create_github_pull_request", {**args, "repository": "acme/payments"}, facts), context)
    gitlab = await gitlab_mrs.CreateGitLabMergeRequestTool().execute(
        mark_fields("create_gitlab_merge_request", {**args, "project": "acme/payments"}, facts), context)
    bitbucket = await bitbucket_prs.CreateBitbucketPullRequest().execute(
        mark_fields("create_bitbucket_pull_request", {**args, "project_key": "PAY", "repo_slug": "payments"}, facts),
        context)

    created = {"github": next(body for url, body in sent["github"] if url.endswith("/pulls"))["body"],
               "gitlab": next(body for url, body in sent["gitlab"] if url.endswith("/merge_requests"))["description"],
               "bitbucket": sent["bitbucket"][0][1]["description"]}
    requested = {"github": next(body for url, body in sent["github"] if url.endswith("/requested_reviewers")),
                 "gitlab": next(body for url, body in sent["gitlab"] if url.endswith("/merge_requests")),
                 "bitbucket": sent["bitbucket"][0][1]}
    if facts is not None:
        return created
    if bot:
        assert [github.get("reviewer_skipped"), gitlab.get("reviewer_skipped"), bitbucket.get("reviewer_skipped")] == [
            None] * 3
        assert set(created.values()) == {"PAY-1"}
        assert requested["github"]["reviewers"] == ["admin-scm", "lead"] and requested["gitlab"]["reviewer_ids"] == [
            41, 42]
        assert requested["bitbucket"]["reviewers"] == [{"user": {"name": "admin-scm"}}, {"user": {"name": "lead"}}]
        return created
    assert {github["reviewer_skipped"], gitlab["reviewer_skipped"], bitbucket["reviewer_skipped"]} == {
        REQUESTER_IS_AUTHOR}
    assert all("Requested by @admin-scm" in text and text.startswith("PAY-1") for text in created.values())
    assert requested["github"]["reviewers"] == ["lead"] and requested["gitlab"]["reviewer_ids"] == [42]
    assert requested["bitbucket"]["reviewers"] == [{"user": {"name": "lead"}}]
    return created


async def test_the_run_records_the_skip_tells_the_requester_and_still_watches_the_merge(db, monkeypatch):
    from tests.agent_definition_revision_fixtures import make_project

    tools = FakeTools(monkeypatch, {"prepare_github_repository": [{"local_path": "repos/payments"}],
                                    "create_github_pull_request": [{
                                        "number": 12, "html_url": "https://scm.test/pr/12", "status": "created",
                                        "reviewers_unresolved": [], "reviewer_skipped": REQUESTER_IS_AUTHOR}]})
    project, admin = await make_project(db), await admin_user(db)
    await _repository(db, project.id, "github", "payments", owners=["lead-dev"])
    db.add(UserLinkedAccount(user_id=admin.id, platform="github", username="admin-scm"))
    item = await _item(db, project_id=project.id)
    definition = {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "branch", "type": "platform_action", "config": {"action": "scm.create_branch"}},
                  {"id": "pr", "type": "platform_action", "config": {"action": "scm.open_pr"}},
                  {"id": "merged", "type": "watch", "config": {"conditions": ["pr.merged"]}},
                  {"id": "ok", "type": "outcome", "config": {"outcome": "delivered"}},
                  {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "branch"},
                  {"id": "2", "source_node_id": "branch", "target_node_id": "pr", "when": "succeeded"},
                  {"id": "3", "source_node_id": "branch", "target_node_id": "ko", "when": "failed"},
                  {"id": "4", "source_node_id": "pr", "target_node_id": "merged", "when": "succeeded"},
                  {"id": "5", "source_node_id": "pr", "target_node_id": "ko", "when": "failed"},
                  {"id": "6", "source_node_id": "merged", "target_node_id": "ok", "when": "pr.merged"}],
    }
    run = await _run(db, definition, work_item_id=item.id, project_id=project.id, repository="github:acme/payments")
    pr_call = next(call for call in tools.calls if call[0] == "create_github_pull_request")
    assert pr_call[1]["requester"] == "admin-scm" and pr_call[1]["reviewers"] == ["admin-scm", "lead-dev"]
    assert (run.status, run.waiting_kind) == ("waiting", "watching")  # the merge gate is unchanged
    assert run.pull_request["reviewer_skipped"] == REQUESTER_IS_AUTHOR and run.pull_request["reviewers"] == ["lead-dev"]
    assert run.context["reviewer_skipped"] == REQUESTER_IS_AUTHOR
    events = [event.kind for event in (await db.execute(
        WorkflowRunEvent.__table__.select().where(WorkflowRunEvent.run_id == run.id))).all()]
    assert "reviewer_skipped" in events
    notice = reviewer_notice(run)
    assert notice["url"] == "https://scm.test/pr/12" and "GitHub" in notice["text"]
    inbox = [entry for entry in await inbox_items(db, admin.id) if entry["id"] == run.id]
    assert [entry["kind"] for entry in inbox] == ["workflow_run_review_own_pr"]
    assert inbox[0]["link"]["href"] == "https://scm.test/pr/12"
