"""PR review bot: ``@octryx fix`` / ``write tests``.

- a fix run pushes only onto an open, non-fork pull request's branch of a repository with ``fix_runs`` on, never onto
  its target or a protected branch, one run per pull request at a time; anything else is answered, nothing starts;
- in a finding's thread it fixes that finding, in the conversation every open blocking one; ``write tests`` changes
  test files only; the person's default engine runs it (a named other engine is answered with a note);
- the run finds the commenter's device folder named like the repository (a repository nobody ran on a device yet);
- ``pr-fix`` never goes through ``scm.create_branch``: the succession rule there is untouched for every workflow.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.models import UserLinkedAccount, WorkflowRun
from app.services.pr_review_bot import comment_poll, fix
from app.services.pr_review_bot.events import pull_request_event
from app.services.pr_review_bot.settings import BotSettings, store_settings
from tests.pr_review_bot_flow_support import HEADERS, _payload, _workspace
from tests.test_pr_review_bot_commands import _comment
from tests.test_pr_review_bot_explain_ignore import _provider, _reviewed

SEEDS = Path(__file__).parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_pr_fix_never_creates_or_adopts_a_branch():
    """The succession rule of ``scm.create_branch`` stays the only way any other workflow reaches a branch."""
    definition = next(item for item in json.loads(SEEDS.read_text()) if item["key"] == "pr-fix")["definition"]
    actions = [node["config"]["action"] for node in definition["nodes"] if node["type"] == "platform_action"]
    assert "scm.create_branch" not in actions and actions[0] == "pr_review.fix_prepare"
    into_push = [(edge["source_node_id"], edge.get("when")) for edge in definition["edges"]
                 if edge["target_node_id"] == "push"]
    assert into_push == [("review", "passed")]  # the push is reached only through the passed review gate
    gate = next(node for node in definition["nodes"] if node["id"] == "review")
    assert gate["config"]["checks"][0]["type"] == "review_passed"  # never a push without a passed review


async def test_a_fix_run_is_refused_unless_every_condition_holds(db):
    project_id, record, _hook = await _workspace(db, trigger="both")
    pr = pull_request_event(_payload("a" * 40), HEADERS)
    assert "fix runs are off" in await fix.refusal(db, project_id, record, pr)
    store_settings(record, BotSettings("both", ("release",), fix_runs=True))
    assert await fix.refusal(db, project_id, record, pr) == ""
    fork = SimpleNamespace(**{**pr.as_context(), "fork": True})
    assert "fork" in await fix.refusal(db, project_id, record, fork)
    protected = SimpleNamespace(**{**pr.as_context(), "source_branch": "release", "fork": False})
    assert "protected" in await fix.refusal(db, project_id, record, protected)
    onto_target = SimpleNamespace(**{**pr.as_context(), "source_branch": pr.target_branch})
    assert "protected" in await fix.refusal(db, project_id, record, onto_target)
    db.add(WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-fix", title="fix",
                       requested_by="u", repository=pr.repository, branch=pr.source_branch,
                       context={"pr_review": {"pr_id": pr.pr_id}}))
    await db.flush()
    assert "already running" in await fix.refusal(db, project_id, record, pr)


def test_the_engine_word_and_test_files():
    assert fix.parse_args("codex keep it small") == ("codex", "keep it small")
    assert fix.parse_args("please keep it small") == ("", "please keep it small")
    globs = list(fix.DEFAULT_TEST_GLOBS)
    assert fix.is_test("tests/test_pay.py", globs) and fix.is_test("pay/test_bulk.py", globs)
    assert not fix.is_test("pay/bulk.py", globs)


async def test_the_commenters_device_folder_named_like_the_repository_is_found(db):
    from app.models.security.device import UserDevice
    from tests.phased_workflow_fixtures import admin_user

    owner = await admin_user(db)
    db.add_all([UserDevice(owner_user_id=owner.id, name="mac", name_key="mac", os="macos", public_key="k",
                           folders=["/Volumes/data/octryx-bench/review-bot-test"], profiles=["seat", "governed"]),
                UserDevice(owner_user_id=owner.id, name="old", name_key="old", os="macos", public_key="k2",
                           folders=["/x/review-bot-test"], profiles=["governed"])])  # no seat: never picked
    await db.flush()
    target = await fix.device_target(db, owner.id, "github:octryx-ai/review-bot-test")
    assert (target["folder"], target["profile"]) == ("/Volumes/data/octryx-bench/review-bot-test", "seat")
    assert await fix.device_target(db, owner.id, "github:acme/other") == "auto"


async def test_fix_in_a_thread_starts_a_run_for_that_finding_and_answers_at_once(db, monkeypatch, tmp_path):
    _project_id, record, _run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    store_settings(record, BotSettings("both", (), fix_runs=True))
    posts = _provider(monkeypatch, head, [_comment("c1", "octryx-ai", "@octryx fix codex keep it small",
                                                   inline=True, in_reply_to="4711")])
    from app.services.pr_review_bot import bot_state, commands

    async def engine(_db, *, user_id, workspace_id):
        return SimpleNamespace(engine="claude_code")

    monkeypatch.setattr("app.services.agent_gateway.engine_policy.effective_engine", engine)
    spawned = []
    monkeypatch.setattr(commands, "spawn", lambda coroutine: spawned.append(coroutine.cr_frame.f_locals) or
                        coroutine.close())
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"fix": 1}
    started = spawned[0]
    assert (started["mode"], started["note"], [item["id"] for item in started["findings"]]) == (
        "fix", "keep it small", ["F1"])
    answer = posts[0]["thread_answers"][0]["reply"]
    assert answer.startswith("🔧 Octryx is starting a run for a fix of F1") and "default engine (claude_code)" in answer


async def test_fix_without_the_opt_in_or_without_open_findings_is_answered_and_starts_nothing(
        db, monkeypatch, tmp_path):
    _project_id, record, run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    posts = _provider(monkeypatch, head, [_comment("c1", "octryx-ai", "@octryx fix")])
    from app.services.pr_review_bot import bot_state, commands

    monkeypatch.setattr(commands, "spawn", lambda coroutine: (_ for _ in ()).throw(AssertionError("started")))
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"refused": 1}
    assert "fix runs are off" in posts[-1]["comment"]
    store_settings(record, BotSettings("both", (), fix_runs=True))
    run.context = {**run.context, "pr_review": {**run.context["pr_review"], "open_findings": []}}
    await db.commit()
    posts.clear()
    import app.services.pr_review_bot.comment_poll as poll

    monkeypatch.setattr(poll, "_now", lambda: __import__("datetime").datetime.now(__import__("datetime").UTC))
    from tests.test_pr_review_bot_explain_ignore import _provider as provider

    posts = provider(monkeypatch, head, [_comment("c2", "octryx-ai", "@octryx fix")])
    assert await comment_poll.poll_comments(db, record, owner.id) == {"refused": 1}
    assert "no open blocking finding" in posts[-1]["comment"]


async def test_the_steps_check_out_the_pr_branch_scope_the_change_and_answer(db, monkeypatch, tmp_path):
    from tests.pr_review_bot_flow_support import _origin, _tools

    clone, head = _origin(tmp_path)
    tools = _tools(monkeypatch, clone)
    project_id, record, _hook = await _workspace(db, trigger="both")
    store_settings(record, BotSettings("both", (), fix_runs=True))
    pr = pull_request_event(_payload(head), HEADERS)
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-fix", title="fix",
                      requested_by="u", repository=pr.repository, branch=pr.source_branch, context={
                          "pr_review": {**pr.as_context(), "fix": {"mode": "tests", "findings": [], "inline": False,
                                                                   "comment_id": "c1", "author": "octryx-ai"}}})
    db.add(run)
    await db.flush()
    prepared = await fix.fix_prepare(db, run, {})
    assert prepared.ok and run.context["base_sha"] == head  # the fix starts from the pull request's head
    root = Path(run.context["local_path"])
    (root / "totals.py").write_text("changed\n")
    scoped = await fix.fix_scope(db, run, {})
    assert not scoped.ok and "may only add or change tests" in scoped.reason and "totals.py" in scoped.reason
    _git(root, "checkout", "--", "totals.py")
    (root / "tests").mkdir()
    (root / "tests/test_totals.py").write_text("def test_rounds():\n    assert True\n")
    assert (await fix.fix_scope(db, run, {})).ok
    run.context = {**run.context, "head_sha": "b" * 40}
    await fix.fix_report(db, run, {"outcome": "pushed"})
    reply = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert reply["comment"].startswith(f"🔧 Octryx pushed `bbbbbbb` to `{pr.source_branch}`: adds tests")
    run.context = {**run.context, "actions": {"push": {"action": "scm.push", "result": "failed",
                                                       "reason": "non-fast-forward"}}}
    await fix.fix_report(db, run, {"outcome": "failed"})
    reply = [call[1] for call in tools.calls if call[0] == "post_github_pull_request_review"][-1]
    assert "could not finish the tests: non-fast-forward" in reply["comment"] and "Nothing was pushed" in reply[
        "comment"]
    store_settings(record, BotSettings("both", (pr.source_branch,), fix_runs=True))
    refused = await fix.fix_prepare(db, run, {})  # checked again when the run starts
    assert not refused.ok and "protected" in refused.reason
    assert UserLinkedAccount  # (imported for the shared fixtures)


async def test_a_started_fix_run_checks_out_the_branch_and_reaches_its_fix_phase(db, monkeypatch, tmp_path):
    from tests.pr_review_bot_flow_support import _origin, _tools

    clone, head = _origin(tmp_path)
    _tools(monkeypatch, clone, prepare_workspace=[{"local_path": str(clone)}])
    project_id, record, _hook = await _workspace(db, trigger="both")
    store_settings(record, BotSettings("both", (), fix_runs=True))
    from tests.phased_workflow_fixtures import admin_user

    owner = await admin_user(db)
    from app.models.security.device import UserDevice

    db.add(UserDevice(owner_user_id=owner.id, name="mac", name_key="mac", os="macos", public_key="k",
                      folders=[str(clone)], profiles=["seat"]))  # the clone is named like the repository: "pay"
    await db.flush()
    chosen = []

    async def validated(_db, *, user, project_id, raw, repository=None):
        chosen.append(raw)  # the Workspace's seat policy is tested elsewhere; here: the target fix_prepare asks for
        return {**raw, "device_name": "mac"} if isinstance(raw, dict) else None

    monkeypatch.setattr("app.services.workflow_runs.runtime_target.target.validate_target", validated)
    pr = pull_request_event(_payload(head), HEADERS)
    event = SimpleNamespace(comment_id="c1", author="octryx-ai", thread_root="4711", inline=True, author_id="")
    findings = [{"id": "F1", "severity": "high", "file": "totals.py", "line": 3, "fix": "Round half up."}]
    run_id = await fix.start_fix(db, project_id, pr, event, owner.id, mode="fix", findings=findings, note="",
                                 engine="")
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert chosen[0]["kind"] == "device" and chosen[0]["folder"] == str(clone)
    assert run.context["base_sha"] == head and run.context["handoff"]["pr_fix"]["findings"][0]["id"] == "F1"
    assert run.current_node_id in ("prepare", "fix") and run.outcome is None
    assert run.title == "Fix F1: Round half up. (octryx review)"  # the subject of the commit scm.push makes
    assert run.context["commit_body"].startswith("- F1 totals.py:3 [high] Round half up.")


def test_the_report_names_the_failed_step_never_the_findings_the_run_started_with():
    """When fix_prepare fails on the repository's operations, the answer names that failure; it must not say the
    review had not passed the fix, quoting the finding the run was started with."""
    started_with = {"verdict": "changes", "node_id": "independent_review", "findings": [
        {"id": "F1", "severity": "high", "file": "pay/bulk.py", "line": 31, "fix": "Export bulk_savings."}]}
    refused = WorkflowRun(context={"review": started_with, "actions": {"fix_prepare": {
        "action": "pr_review.fix_prepare", "result": "failed",
        "reason": "Repository operation 'branch' is denied for acme/pay"}}})
    reason = fix._last_failure(refused)
    assert reason.startswith("Repository operation 'branch' is denied") and "branch and write operations" in reason
    assert "review" not in reason
    nothing = WorkflowRun(context={"review": started_with, "actions": {"fix_prepare": {"result": "succeeded"}}})
    assert fix._last_failure(nothing) == "the run stopped before the push"  # no review ran: none is quoted
    reviewed = WorkflowRun(context={"review": {**started_with, "attempt": "a1"}, "actions": {}})
    assert fix._last_failure(reviewed).startswith("the independent review did not pass the fix: pay/bulk.py:31")


def test_the_fix_commit_says_what_it_fixes_and_links_the_pull_request():
    """The commit message must not read "PR fix" plus the trailers."""
    pr = SimpleNamespace(pr_id="2", url="https://github.com/octryx-ai/review-bot-test/pull/2", provider="github")
    event = SimpleNamespace(author="octryx-ai")
    subject, body = fix.commit_message("fix", [{"id": "F1", "severity": "medium", "file": "pay/bulk.py", "line": 34,
                                                "fix": "Add bulk_savings to __all__ so the public helper is exported "
                                                       "like the others."}], pr, event)
    assert subject == "Fix F1: Add bulk_savings to __all__ so the public helper is… (octryx review)"
    assert body.splitlines() == [
        "- F1 pay/bulk.py:34 [medium] Add bulk_savings to __all__ so the public helper is exported like the others.",
        "", "Pull request: https://github.com/octryx-ai/review-bot-test/pull/2",
        "Requested by @octryx-ai with @octryx fix."]
    assert fix.commit_message("tests", [], pr, event)[0] == "Add tests for pull request #2 (octryx review)"


async def test_fix_on_an_installation_with_pr_fix_switched_off_says_so_and_where_to_switch_it_on(
        db, monkeypatch, tmp_path):
    """``pr-fix`` ships optional and off: a fresh installation answers "No published workflow 'pr-fix'". The answer
    names the workflow as its definition does, and where a platform administrator switches it on."""
    from sqlalchemy import select

    from app.models.runtime.flow_definition import FlowDefinition

    _project_id, record, _run, head, owner, _tools_ = await _reviewed(db, monkeypatch, tmp_path)
    store_settings(record, BotSettings("both", (), fix_runs=True))
    flow = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == "pr-fix"))).scalars().one()
    flow.is_active, flow.name = False, "Pull request fix"  # the name comes from the definition, whatever it says
    await db.flush()
    posts = _provider(monkeypatch, head, [_comment("c1", "octryx-ai", "@octryx fix"),
                                          _comment("c2", "octryx-ai", "@octryx write tests")])
    from app.services.pr_review_bot import bot_state, commands

    monkeypatch.setattr(commands, "spawn", lambda coroutine: (_ for _ in ()).throw(AssertionError("started")))
    bot_state.set_cursor(record, "2026-11-17T19:00:00+00:00")
    assert await comment_poll.poll_comments(db, record, owner.id) == {"refused": 2}
    answers = [post["comment"] for post in posts if "comment" in post]
    assert answers == [
        "Octryx: Fixing pull requests is switched off on this Octryx installation. A platform administrator can turn "
        "on the 'Pull request fix' workflow under Agents › Workflows.",
        "Octryx: Writing tests for pull requests is switched off on this Octryx installation. A platform "
        "administrator can turn on the 'Pull request fix' workflow under Agents › Workflows."]
    flow.is_active = True
    await db.flush()
    assert await fix.switched_off(db, _project_id, fix.MODE_FIX) == ""
