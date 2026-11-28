"""A run's platform actions dispatch in the run's working copy, never the chat session's folder, or the push
tool's own path check refuses the run's copy."""

from __future__ import annotations

import subprocess

import pytest

from app.models import Session
from app.services.session.workspace import resolve_session_workspace_root
from app.services.workflow_runs.platform import dispatch, repo_ref, scm
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.tools.context import ToolContext
from app.tools.registry import TOOL_REGISTRY
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

PATHS = {"bitbucket": "PAY/payments", "github": "acme/payments", "gitlab": "acme/payments"}
INSIDE_ROOT = "must stay inside workspace root"


def _git_copy(root):
    root.mkdir(parents=True)
    (root / "README.md").write_text("payments\n")
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-qm", "c"]):
        subprocess.run(["git", *argv], cwd=root, check=True)
    (root / "README.md").write_text("payments, changed\n")  # the run's change
    return root.resolve()


def _observe(monkeypatch, tool: str) -> list[dict]:
    seen: list[dict] = []
    original = TOOL_REGISTRY[tool].execute

    async def execute(params, context):
        result = await original(params, context)
        seen.append({"root": str(context.workspace_root), "result": result})
        return result

    monkeypatch.setattr(TOOL_REGISTRY[tool], "execute", execute)
    return seen


def _connector_active(monkeypatch, provider: str) -> None:
    async def project_config(_project_id, _db):
        # The run's project has the provider's connector and grants its push (as the live project does).
        return {"connectors": {provider: {"enabled": True}},
                "tool_policy": {"high_risk_grants": [repo_ref.TOOLS[provider]["push"]]}}

    monkeypatch.setattr(dispatch, "get_project_config", project_config)


async def _run(db, tmp_path, provider: str, *, copy: bool = True):
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, phased_definition()),
                          project_id=workspace_id, session=session)
    run.repository, run.branch, run.ticket_key = f"{provider}:{PATHS[provider]}", "feature/BRD-12-truncate", "BRD-12"
    # The re-created copy lives under another base than the session's folder (live: /app/data vs /tmp).
    local = tmp_path / "data" / "session-workspaces" / "s" / "run-copies" / "r" / "payments"
    if copy:
        _git_copy(local)
    run.context = {**dict(run.context or {}), "local_path": str(local), "base_sha": "HEAD"}
    await db.commit()
    session_root = await resolve_session_workspace_root(db, await db.get(Session, await main_session_id(db, run)))
    return run, local, session_root.resolve()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["bitbucket", "github", "gitlab"])
async def test_the_push_checks_the_run_copy_against_the_run_root(db, tmp_path, monkeypatch, provider):
    run, local, session_root = await _run(db, tmp_path, provider)
    assert not local.is_relative_to(session_root)  # the live shape: the copy is outside the session's folder
    _connector_active(monkeypatch, provider)
    seen = _observe(monkeypatch, repo_ref.TOOLS[provider]["push"])

    outcome = await scm.push(db, run, {})

    assert [call["root"] for call in seen] == [str(local)], outcome  # the provider tool ran in the run's copy
    assert INSIDE_ROOT not in str(seen[0]["result"]) and INSIDE_ROOT not in outcome.reason, outcome
    # Past the path and git checks, the tool reached its next gate (the project's repository write policy).
    assert "project repository policy" in str(seen[0]["result"].get("error")), seen


@pytest.mark.asyncio
async def test_a_path_outside_the_run_copy_is_still_refused(db, tmp_path, monkeypatch):
    run, _local, _session_root = await _run(db, tmp_path, "bitbucket")
    seen = _observe(monkeypatch, "commit_and_push_repository_branch")
    elsewhere = _git_copy(tmp_path / "elsewhere")

    outcome = await dispatch.dispatch_tool(db, run, "commit_and_push_repository_branch", {
        "project_key": "PAY", "repo_slug": "payments", "local_path": str(elsewhere), "commit_message": "x",
        "branch_name": run.branch}, capability_class="deliver")

    assert (outcome.state, outcome.failure_class) == ("failed", "not_configured")
    assert "must stay inside the run's working copy" in outcome.reason and seen == []
    # The tool's own check stays: given a root, a path outside it is refused (tool use outside runs is unchanged).
    context = ToolContext(user_id="u", project_ids=[], roles=[], session_id=None, project_config={},
                          workspace_root=str(tmp_path / "data"), db=db)
    refused = await TOOL_REGISTRY["commit_and_push_repository_branch"].execute(
        {"local_path": str(elsewhere), "commit_message": "x"}, context)
    assert INSIDE_ROOT in str(refused.get("error"))


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [True, False])
async def test_a_run_without_its_copy_refuses_the_push_without_a_fallback(db, tmp_path, monkeypatch, declared):
    run, local, _session_root = await _run(db, tmp_path, "github", copy=False)
    if not declared:
        run.context = {key: value for key, value in dict(run.context or {}).items() if key != "local_path"}
    seen = _observe(monkeypatch, "commit_and_push_github_repository_branch")

    outcome = await dispatch.dispatch_tool(db, run, "commit_and_push_github_repository_branch", {
        "owner": "acme", "repo": "payments", "local_path": str(local), "commit_message": "x",
        "branch_name": run.branch}, capability_class="deliver")

    assert (outcome.state, outcome.failure_class) == ("failed", "not_configured") and seen == []
    assert outcome.reason == (dispatch.COPY_MISSING_REASON if declared else dispatch.NO_COPY_REASON)
    if declared:  # the run-level push names the same refusal
        assert (await scm.push(db, run, {})).reason == dispatch.COPY_MISSING_REASON


@pytest.mark.asyncio
async def test_prepare_and_api_only_actions_keep_their_roots(db, tmp_path):
    run, local, session_root = await _run(db, tmp_path, "bitbucket")
    # A prepare call establishes copies in the session's folder; any other action of a run with a copy uses the copy.
    assert dispatch.run_root(run, "prepare_bitbucket_repository", {"branch_name": "b"}) == (None, "")
    assert dispatch.run_root(run, "create_bitbucket_pull_request", {}) == (str(local), "")
    # A run without a copy: an API-only action keeps the session's folder (it reads no file).
    run.context = {}
    assert dispatch.run_root(run, "create_bitbucket_pull_request", {}) == (None, "")
    context = await dispatch.tool_context(db, run, "deliver")
    assert context.workspace_root == str(session_root)
