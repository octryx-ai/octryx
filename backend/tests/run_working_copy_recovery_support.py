"""Shared helpers for the test_run_working_copy_recovery_* modules."""

from __future__ import annotations

import copy
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Session, WorkflowRunEvent
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.platform import dispatch as dispatch_module
from app.services.workflow_runs.records import main_session_id, new_chat_session, start_run
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from app.tools.registry import TOOL_REGISTRY
from tests.phased_workflow_fixtures import admin_user, phased_definition, publish_phased, run_workspace

BRANCH = "feature/BRD-12-add-a-truncate-words-function-to-textkit"


SECRET = "SECRET-TOKEN-4711"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


def _origin(tmp_path: Path, *, branch: bool = True) -> tuple[Path, Path, str]:
    """A bare origin: ``main`` at the run's base (with the slugify tests), the run's branch created empty at it."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    (seed / "tests").mkdir()
    (seed / "tests" / "test_textkit.py").write_text("def test_slugify_lowercases():\n    pass\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "main with slugify")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    if branch:
        _git(seed, "push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}")
    return origin, seed, _git(seed, "rev-parse", "HEAD")


REMOTE = "https://bitbucket.org/demo-team/test.git"  # the run's repository as the connector's clone names it


def _provider_tool(monkeypatch, origin: Path, *, fail: str = "", during=None, remote: str = REMOTE) -> list[dict]:
    """The provider's prepare tool, as it behaves: clone under the context's workspace, branch from the base."""
    calls: list[dict] = []

    async def execute(params, context):
        calls.append({"params": dict(params), "workspace_root": context.workspace_root})
        if fail:
            return {"error": fail}
        if during is not None:
            await during()
        path = Path(context.workspace_root) / "var/repos/bitbucket" / params["project_key"] / params["repo_slug"]
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(path.parent, "clone", "-q", "--branch", "main", str(origin), str(path))
        _git(path, "checkout", "-q", "-B", params["branch_name"])  # the real tool branches from the base
        _git(path, "remote", "set-url", "origin", remote)  # the connector's clone URL (no credential in it)
        return {"local_path": str(path), "base_branch": "main", "branch_name": params["branch_name"],
                "remote_url": f"https://x-token-auth:{SECRET}@bitbucket.org/demo-team/test.git"}

    async def project_config(project_id, db):  # the run's Workspace: Bitbucket active, the prepare tool allowed
        return {"connectors": {"bitbucket": {"enabled": True}},
                "tool_policy": {"allowlist": ["prepare_bitbucket_repository"]}}

    async def hosts(db, run, provider, repo_args):  # the host of the run's named Bitbucket connection
        return {"bitbucket.org"}

    monkeypatch.setattr(TOOL_REGISTRY["prepare_bitbucket_repository"], "execute", execute)
    monkeypatch.setattr(dispatch_module, "get_project_config", project_config)
    monkeypatch.setattr("app.services.agent_gateway.repository_root.connection_hosts", hosts)
    return calls


def _definition(capability_class: str = "read_only") -> dict:
    definition = copy.deepcopy(phased_definition())
    definition["nodes"][1]["config"]["workflow_contract"]["capability_class"] = capability_class
    return definition


async def _held_run(db, tmp_path, monkeypatch, *, base_sha: str, recorded: Path, capability_class: str = "read_only",
                    head_sha: str = ""):
    persistent = tmp_path / "persistent-data" / "session-workspaces"
    monkeypatch.setenv("OCTRYX_SESSION_WORKSPACE_BASE_DIR", str(persistent))
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    # The session's own root was recorded under the old, non-persistent base (gone with the container).
    session.metadata_ = {**dict(session.metadata_ or {}), "workspace_root": str(tmp_path / "old-tmp" / session.id)}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition(capability_class)),
                          project_id=workspace_id,
                          session=session)
    run.repository, run.branch = "bitbucket:demo-team/test", BRANCH
    run.context = {**dict(run.context or {}), "local_path": str(recorded), "base_sha": base_sha,
                   PREPARATION_KEY: {"state": "ready", "runtime": "server"},
                   **({"head_sha": head_sha} if head_sha else {})}
    await db.flush()
    held = await run_turn_resolution(db, await db.get(Session, session.id), user_message="Work.")
    return admin, run, held, persistent


async def _events(db, run) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars())


def _report(run) -> dict:
    return dict(run.context[PREPARATION_KEY].get("report") or {}).get("branch") or {}


async def _resolution(db, run) -> dict:
    session = await db.get(Session, await main_session_id(db, run))
    return await run_turn_resolution(db, session, user_message="Work.")


@pytest.fixture(autouse=True)
def _server_pipeline(monkeypatch):
    """The server pipeline's own mechanics: the server build lock is lifted here (``tests.server_build_lock``)."""
    from tests.server_build_lock import lift_server_build_lock

    lift_server_build_lock(monkeypatch)


@pytest.fixture(autouse=True)
def _git_stays_offline(monkeypatch):
    """The runs name their repository by its real remote (``REMOTE``); the WIP fetch toward it is best effort and its
    failure is what these tests go through. Git refuses every transport but ``file`` here, so that failure is
    immediate: no network, no credential prompt from an inherited askpass (otherwise each such test can wait for
    the 120 s git timeout while an editor's askpass asks for a password)."""
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    for name in ("GIT_ASKPASS", "SSH_ASKPASS", "VSCODE_GIT_ASKPASS_MAIN", "VSCODE_GIT_IPC_HANDLE"):
        monkeypatch.delenv(name, raising=False)
