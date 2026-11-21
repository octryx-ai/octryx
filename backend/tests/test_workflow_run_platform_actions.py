"""DevOps workflows S4: typed platform actions of a run on the server (Jira, SCM, CI), and a tool approval WAITS."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import CodeRepository, UserLinkedAccount, WorkflowRun
from app.models.runtime.secure_work import WorkItem, WorkItemWorkflowDefinition, WorkPullRequest
from app.services.approval.resolution_service import decide_pending_approval
from app.services.flow_definitions import validate_flow_definition
from app.services.linked_accounts.resolution import scm_platform
from app.services.workflow_runs.platform import ci, jira, pr_adoption, repo_ref, scm
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.platform.dispatch import ToolOutcome, read_outcome
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import admin_user, join_workspace, publish_phased, run_workspace


def _definition(action: str, params: dict | None = None) -> dict:
    return {
        "execution_kind": "phased",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "act", "type": "platform_action", "label": action, "config": {"action": action, "params": params or {}}},
            {"id": "ok", "type": "outcome", "config": {"outcome": "done"}},
            {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}},
        ],
        "edges": [
            {"id": "a", "source_node_id": "start", "target_node_id": "act"},
            {"id": "b", "source_node_id": "act", "target_node_id": "ok", "when": "succeeded"},
            {"id": "c", "source_node_id": "act", "target_node_id": "ko", "when": "failed"},
        ],
    }


class FakeTools:
    """The governed tool dispatch, scripted: every call is recorded with its arguments."""

    def __init__(self, monkeypatch, answers: dict[str, list[dict]]):
        self.calls: list[tuple[str, dict, str]] = []
        self.answers = answers

        async def dispatch(db, run, tool, arguments, *, capability_class, typed_action=None):
            self.calls.append((tool, arguments, capability_class))
            queue = self.answers.get(tool) or [{"status": "ok"}]
            return read_outcome(queue.pop(0) if len(queue) > 1 else queue[0])

        for module in (dispatch_module, jira, scm, ci, pr_adoption):
            monkeypatch.setattr(module, "dispatch_tool", dispatch, raising=False)
        import app.services.workflow_runs.platform_actions as actions

        monkeypatch.setattr(actions, "dispatch_tool", dispatch)

    def tools(self) -> list[str]:
        return [call[0] for call in self.calls]


async def _item(db, *, project_id: str | None = None, source_type: str = "jira") -> WorkItem:
    item = WorkItem(source_type=source_type, source_instance="test", source_key=f"PAY-{uuid.uuid4().hex[:4].upper()}",
                    source_project_key="PAY", title="Totals round down", project_id=project_id, work_state="development")
    db.add(item)
    await db.flush()
    return item


async def _run(db, definition: dict, **start) -> WorkflowRun:
    admin = await admin_user(db)
    if start.get("project_id"):
        await join_workspace(db, admin, start["project_id"])  # the requester, a member like a real one
    else:
        start["project_id"] = await run_workspace(db, admin, start.get("work_item_id"))
    key = await publish_phased(db, definition)
    session = await new_chat_session(db, admin, start["project_id"])
    return await start_run(db, user=admin, workflow_key=key, session=session, **start)


def test_typed_actions_are_closed_and_never_carry_a_raw_jira_status():
    assert validate_flow_definition(_definition("jira.transition", {"work_state": "review"}))["valid"]
    codes = lambda definition: [error["code"] for error in validate_flow_definition(definition)["errors"]]  # noqa: E731
    assert "raw_status_forbidden" in codes(_definition("jira.transition", {"status": "In Review"}))
    assert "missing_action_param" in codes(_definition("jira.transition"))
    assert "unknown_platform_action" in codes(_definition("jira.delete_project"))
    ci_status = _definition("ci.status")
    ci_status["edges"].append({"id": "d", "source_node_id": "act", "target_node_id": "ko", "when": "running"})
    assert validate_flow_definition(ci_status)["valid"]
    assert read_outcome({"approval_required": True, "approval_id": "a1", "approval_status": "pending"}).state == (
        "approval_pending")


@pytest.mark.asyncio
async def test_jira_issue_comment_and_a_follow_up_issue_recorded_once(db, monkeypatch):
    tools = FakeTools(monkeypatch, {"create_jira_ticket": [{"ticket_id": "PAY-7", "status": "created"},
                                                          {"ticket_id": "PAY-8", "status": "created"}]})
    item = await _item(db)
    run = await _run(db, _definition("jira.create_issue", {"issue_type": "Bug"}))
    assert run.ticket_key is None and run.outcome == "blocked"  # no Work item, no project: an explicit failure
    existing = await _run(db, _definition("jira.create_issue", {"issue_type": "Bug"}), work_item_id=item.id)
    assert (existing.outcome, existing.ticket_key, tools.calls) == ("done", item.source_key, [])  # never twice
    # A "platform" item never goes to Jira; an item without a ticket yet is a "manual" one.
    unticketed = await _item(db, source_type="manual")
    run = await _run(db, _definition("jira.create_issue", {"issue_type": "Bug"}), work_item_id=unticketed.id)
    assert (run.outcome, run.ticket_key, tools.calls[-1][1]["project_key"], tools.calls[-1][2]) == (
        "done", "PAY-7", "PAY", "deliver")
    follow = await _run(db, _definition("jira.create_issue", {"issue_type": "Task", "follow_up": True}),
                        work_item_id=item.id)
    assert follow.context["follow_up_issue"] == "PAY-8"
    assert tools.calls[-1] == ("add_jira_comment", {"ticket_id": item.source_key, "body": "Follow-up issue: PAY-8"},
                               "deliver")
    assert "Follow-up of" in [call for call in tools.calls if call[0] == "create_jira_ticket"][-1][1]["summary"]


@pytest.mark.asyncio
async def test_a_jira_status_moves_only_through_the_write_back_mapping(db, monkeypatch):
    FakeTools(monkeypatch, {})
    admin = await admin_user(db)
    db.add(WorkItemWorkflowDefinition(name="wb", states_json=[], mappings_json={"review": {"sync_back": False}},
                                      sync_policy_json={"sync_mode": "dry_run_only"}, is_default=True,
                                      is_active=True, created_by=admin.id, updated_by=admin.id))
    item = await _item(db)
    run = await _run(db, _definition("jira.transition", {"work_state": "review"}), work_item_id=item.id)
    assert (run.outcome, item.work_state) == ("done", "review")
    unknown = await _run(db, _definition("jira.transition", {"work_state": "no_such_state"}), work_item_id=item.id)
    # No write-back maps this state, so Jira is left untouched: a visible skip and the run continues.
    assert (unknown.outcome, unknown.context["actions"]["act"]["result"]) == ("done", "succeeded")
    skipped = await jira.transition(db, unknown, {"work_state": "no_such_state"})
    assert (skipped.ok, skipped.result["status"], skipped.result["work_state"]) == (True, "skipped", "no_such_state")
    assert "no write-back definition knows" in skipped.result["note"]


async def _repository(db, project_id: str, provider: str, name: str, *, owners: list[str], rule: str = "") -> None:
    setup = {"owners": owners, **({"branch_naming_rule": rule} if rule else {})}
    db.add(CodeRepository(project_id=project_id, provider=provider, name=name, is_active=True, repo_root="/srv/repos",
                          config_json={"coding_setup": setup}))
    await db.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "path", "pr_tool", "result"), [
    ("github", "acme/payments", "create_github_pull_request", {"number": 12, "html_url": "https://scm.test/pr/12"}),
    ("gitlab", "acme/payments", "create_gitlab_merge_request", {"iid": 5, "web_url": "https://scm.test/mr/5"}),
    ("bitbucket", "PAY/payments", "create_bitbucket_pull_request", {"id": 3, "url": "https://scm.test/pr/3"}),
])
async def test_branch_push_and_pr_with_the_requester_as_reviewer_on_every_scm(db, monkeypatch, provider, path,
                                                                             pr_tool, result):
    from tests.agent_definition_revision_fixtures import make_project

    tools = FakeTools(monkeypatch, {f"{repo_ref.TOOLS[provider]['prepare']}": [{"local_path": "repos/payments"}],
                                    pr_tool: [{**result, "status": "created", "reviewers_unresolved": []}]})
    project = await make_project(db)
    admin = await admin_user(db)
    await _repository(db, project.id, provider, "payments", owners=["lead-dev"])
    item = await _item(db, project_id=project.id)
    definition = {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start"},
                  {"id": "branch", "type": "platform_action", "config": {"action": "scm.create_branch",
                                                                         "params": {"branch_type": "bugfix"}}},
                  {"id": "push", "type": "platform_action", "config": {"action": "scm.push"}},
                  {"id": "pr", "type": "platform_action", "config": {"action": "scm.open_pr"}},
                  {"id": "ok", "type": "outcome", "config": {"outcome": "delivered"}},
                  {"id": "ko", "type": "outcome", "config": {"outcome": "blocked"}}],
        "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "branch"},
                  {"id": "2", "source_node_id": "branch", "target_node_id": "push", "when": "succeeded"},
                  {"id": "3", "source_node_id": "branch", "target_node_id": "ko", "when": "failed"},
                  {"id": "4", "source_node_id": "push", "target_node_id": "pr", "when": "succeeded"},
                  {"id": "5", "source_node_id": "push", "target_node_id": "ko", "when": "failed"},
                  {"id": "6", "source_node_id": "pr", "target_node_id": "ok", "when": "succeeded"},
                  {"id": "7", "source_node_id": "pr", "target_node_id": "ko", "when": "failed"}],
    }
    run = await _run(db, definition, work_item_id=item.id, project_id=project.id, repository=f"{provider}:{path}")
    # An unlinked requester never blocks the pull request: opened without them, mentioned, recorded.
    assert run.outcome == "delivered", run.context
    unlinked = next(call for call in tools.calls if call[0] == pr_tool)[1]
    assert unlinked["reviewers"] == ["lead-dev"] and "requester" not in unlinked
    assert "account is not linked" in unlinked["description"]
    assert run.pull_request["reviewer_skipped"] == "requester_unresolved"
    db.add(UserLinkedAccount(user_id=admin.id, platform=scm_platform(provider), username="admin-scm"))
    item = await _item(db, project_id=project.id)
    tools.calls.clear()
    run = await _run(db, definition, work_item_id=item.id, project_id=project.id, repository=f"{provider}:{path}")
    assert run.outcome == "delivered", run.context
    assert run.branch == f"bugfix/{item.source_key}-totals-round-down"
    pr_call = next(call for call in tools.calls if call[0] == pr_tool)
    assert pr_call[1]["reviewers"] == ["admin-scm", "lead-dev"] and pr_call[1]["from_branch"] == run.branch
    assert run.pull_request["provider"] == provider and run.pull_request["url"].startswith("https://scm.test/")
    recorded = (await db.execute(select(WorkPullRequest).where(WorkPullRequest.work_item_id == item.id))).scalars()
    assert [row.provider for row in recorded] == [provider]


@pytest.mark.asyncio
async def test_a_tool_approval_makes_the_step_wait_and_the_grant_runs_it(db, monkeypatch):
    from app.models import Approval

    admin = await admin_user(db)
    approval = Approval(requested_by=admin.id, action="Approve tool execution for add_jira_comment", status="pending")
    db.add(approval)
    await db.flush()
    tools = FakeTools(monkeypatch, {"add_jira_comment": [
        {"approval_required": True, "approval_id": approval.id, "approval_status": "pending"},
        {"status": "created"},
    ]})
    item = await _item(db)
    run = await _run(db, _definition("jira.comment", {"text_from": "work_item"}), work_item_id=item.id)
    assert (run.status, run.waiting_kind) == ("waiting", "awaiting_tool_approval")
    from app.services.workflow_runs.actions import available_actions

    assert [action["key"] for action in await available_actions(db, run, access="write", user=admin)][:2] == [
        "approve_tool", "reject_tool"]
    from app.services.workflow_runs.records import main_session_id

    approval.session_id = await main_session_id(db, run)  # a chat tool approval of the run's session
    await decide_pending_approval(db, approval_id=approval.id, resolved_by=admin.id, status="approved")
    assert (run.status, run.outcome) == ("completed", "done")
    assert tools.tools() == ["add_jira_comment", "add_jira_comment"]


@pytest.mark.asyncio
async def test_a_run_comment_carries_the_ai_marker_but_the_work_items_own_text_does_not(db, monkeypatch):
    """EU AI Act Art. 50(2): the platform's jira.comment marks AI text with the model of the run's main session."""
    from app.models import Message
    from app.services.workflow_runs.records import main_session_id

    tools = FakeTools(monkeypatch, {"add_jira_comment": [{"status": "created"}]})
    item = await _item(db)
    run = await _run(db, _definition("jira.comment", {"text_from": "work_item"}), work_item_id=item.id)
    db.add(Message(session_id=await main_session_id(db, run), role="assistant", content="x", model="claude-haiku-5-5"))
    await db.flush()

    await jira.comment(db, run, {"text_from": "findings"})
    assert tools.calls[-1][1]["body"].endswith(f"\n\n— Written by AI (octryx · claude-haiku-5-5) in run {item.source_key}.")
    await jira.comment(db, run, {"text_from": "work_item"})
    assert "Written by AI" not in tools.calls[-1][1]["body"]


def test_jenkins_test_reports_become_per_test_results():
    report = {"suites": [{"cases": [
        {"className": "tests.test_totals", "name": "test_rounds_half_up", "status": "FAILED"},
        {"className": "tests.test_totals", "name": "test_zero", "status": "PASSED"},
        {"className": "tests.test_totals", "name": "test_slow", "status": "SKIPPED"},
    ]}]}
    from app.services.workflow_checks.test_ids import Resolver
    from app.services.workflow_runs.test_resolution import resolve_entry

    parsed = ci.jenkins_tests(report)  # className + name: keyed canonically once the run knows the file
    assert parsed.results == {} and len(parsed.unresolved) == 3
    entry = resolve_entry({"results": {}, **parsed.fields()}, Resolver(["tests/test_totals.py"]))
    assert {test_id: value["outcome"] for test_id, value in entry["results"].items()} == {
        "tests/test_totals.py::test_rounds_half_up": "failed", "tests/test_totals.py::test_zero": "passed",
        "tests/test_totals.py::test_slow": "skipped"}
    assert repo_ref.parse_repository("gitlab:group/sub/project").path == "group/sub/project"
    assert repo_ref.parse_repository("svn:repo") is None
    assert isinstance(ToolOutcome("succeeded"), ToolOutcome)


@pytest.mark.asyncio
async def test_github_and_gitlab_pull_requests_request_the_named_reviewers(monkeypatch):
    import app.tools.connectors.github_pull_requests as github_prs
    import app.tools.connectors.gitlab_merge_requests as gitlab_mrs
    from app.tools.context import ToolContext

    calls: list[tuple[str, str, dict]] = []

    async def github_http(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json_body") or {}))
        if url.endswith("/requested_reviewers"):
            return {"requested_reviewers": [{"login": "admin-scm"}]}
        return {"number": 9, "html_url": "https://scm.test/pr/9", "head": {"ref": "b"}, "base": {"ref": "main"}}

    async def gitlab_http(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json_body") or kwargs.get("params") or {}))
        if url.endswith("/users"):
            return [{"id": 41, "username": "admin-scm"}] if kwargs["params"]["username"] == "admin-scm" else []
        return {"iid": 2, "web_url": "https://scm.test/mr/2", "reviewers": [{"username": "admin-scm"}]}

    async def allowed(*_args, **_kwargs):
        return None

    async def headers(_context):
        return {}

    monkeypatch.setattr(github_prs, "_http_json", github_http)
    monkeypatch.setattr(github_prs, "require_github_repository_operation", allowed)
    monkeypatch.setattr(github_prs, "_github_headers", headers)
    monkeypatch.setattr(gitlab_mrs, "_http_json", gitlab_http)
    monkeypatch.setattr(gitlab_mrs, "require_gitlab_repository_operation", allowed)
    monkeypatch.setattr(gitlab_mrs, "_gitlab_headers", headers)
    context = ToolContext(user_id="u", project_ids=["p"], roles=[], session_id="s",
                          project_config={"github_url": "https://scm.test/api/v3", "gitlab_url": "https://gl.test"})
    github = await github_prs.CreateGitHubPullRequestTool().execute(
        {"repository": "acme/payments", "title": "t", "from_branch": "b", "to_branch": "main",
         "reviewers": ["admin-scm"]}, context)
    assert github["reviewers"] == ["admin-scm"] and github["reviewers_unresolved"] == []
    assert calls[-1][2] == {"reviewers": ["admin-scm"]}
    gitlab = await gitlab_mrs.CreateGitLabMergeRequestTool().execute(
        {"project": "acme/payments", "title": "t", "from_branch": "b", "to_branch": "main",
         "reviewers": ["admin-scm", "ghost"]}, context)
    assert gitlab["reviewers_unresolved"] == ["ghost"]
    assert calls[-1][2]["reviewer_ids"] == [41]
