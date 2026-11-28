"""A push or pull request only for the server-held tree the run's CI pipeline ran green on; otherwise one
re-run of the pipeline, then a ``pipeline_not_for_head`` pause."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from app.services.workflow_runs import pipeline, pipeline_head, pipeline_report
from app.services.workflow_runs.binding import run_turn_resolution
from app.services.workflow_runs.platform.dispatch import SUCCEEDED, ToolOutcome
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.phased_workflow_fixtures import PHASE, admin_user, phase_turn, publish_phased, run_workspace
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

COMMANDS = [".venv/bin/python -m pytest -q"]


def _definition(with_pipeline: bool = True) -> dict:
    nodes = [{"id": "start", "type": "start"},
             {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
             {"id": "push", "type": "platform_action", "label": "Push", "config": {"action": "scm.push"}},
             {"id": "pr", "type": "platform_action", "label": "Pull request", "config": {"action": "scm.open_pr"}},
             {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
             {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}]
    edges = [{"id": "a", "source_node_id": "start", "target_node_id": "work"},
             {"id": "p1", "source_node_id": "push", "target_node_id": "pr", "when": "succeeded"},
             {"id": "p2", "source_node_id": "push", "target_node_id": "blocked", "when": "failed"},
             {"id": "r1", "source_node_id": "pr", "target_node_id": "done", "when": "succeeded"},
             {"id": "r2", "source_node_id": "pr", "target_node_id": "blocked", "when": "failed"}]
    if with_pipeline:
        nodes.append({"id": "pipeline", "type": "platform_action", "label": "CI",
                      "config": {"action": "pipeline.run"}})
        edges += [{"id": "b", "source_node_id": "work", "target_node_id": "pipeline"},
                  {"id": "c", "source_node_id": "pipeline", "target_node_id": "push", "when": "succeeded"},
                  {"id": "d", "source_node_id": "pipeline", "target_node_id": "work", "when": "failed",
                   "kind": "loop", "max_iterations": 3}]
    else:
        edges.append({"id": "b", "source_node_id": "work", "target_node_id": "push"})
    return {"execution_kind": "phased", "nodes": nodes, "edges": edges}


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class Repo:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        _git(root, "init", "-q")
        _git(root, "config", "user.name", "t")
        _git(root, "config", "user.email", "t@t.invalid")
        (root / "app.py").write_text("print('base')\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "base")
        self.base = _git(root, "rev-parse", "HEAD")

    def change(self, files: dict[str, str]) -> tuple[str, str]:
        for name, text in files.items():
            (self.root / name).write_text(text)
        _git(self.root, "add", "-A")
        tree = _git(self.root, "write-tree")
        patch = _git(self.root, "diff", "--cached", "--binary", self.base) + "\n"
        _git(self.root, "reset", "-q", "--hard", self.base)
        _git(self.root, "clean", "-fdq")
        return patch, tree


@pytest.fixture
def scm_calls(monkeypatch):
    calls: list[str] = []

    async def push(_db, run, _params):
        calls.append("push")
        context = dict(run.context or {})
        head = _git(Path(context["local_path"]), "commit-tree", context["review"]["tree"], "-p", context["base_sha"],
                    "-m", "pushed")
        run.context = {**context, "head_sha": head}
        return ToolOutcome(SUCCEEDED, {"head_commit": head})

    async def open_pr(_db, _run, _params):
        calls.append("pr")
        return ToolOutcome(SUCCEEDED, {"id": 7})

    monkeypatch.setattr("app.services.workflow_runs.platform.scm.push", push)
    monkeypatch.setattr("app.services.workflow_runs.platform.scm.open_pr", open_pr)
    return calls


async def _run(db, monkeypatch, *, with_pipeline: bool = True, runtime: str = "device"):
    async def commands(_db, _run):
        return list(COMMANDS), [], COMMANDS[-1] if len(COMMANDS) > 1 else ""

    async def runtime_of(_db, _run):
        return runtime

    async def no_turn(_db, _run, _node):
        return None

    monkeypatch.setattr(pipeline, "commands_for", commands)
    monkeypatch.setattr("app.services.workflow_runs.workspace.preparation.runtime_of", runtime_of)
    monkeypatch.setattr("app.services.workflow_runs.octryx.continuation.runtime_step_entered", no_turn)
    admin = await admin_user(db)
    workspace_id = await run_workspace(db, admin)
    session = await new_chat_session(db, admin, workspace_id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition(with_pipeline)),
                          project_id=workspace_id,
                          session=session)
    return run, session, admin


async def _phase_done(db, session):
    resolution = await run_turn_resolution(db, session, user_message="Build it.")
    await phase_turn(db, session.id, resolution, ["knowledge_search"])


def _holds(run, repo: Repo, patch: str, reviewed: str) -> None:
    run.context = {**dict(run.context or {}), "local_path": str(repo.root), "base_sha": repo.base,
                   "device_change": {"base": repo.base, "patch": patch}, "review": {"tree": reviewed}}


def _report(run, code: int = 0, tree: str | None = None) -> dict:
    view = pipeline.contract_view(run)
    return {"node_id": view["node_id"], "entry": view["entry"], **({"tree": tree} if tree else {}),
            "results": [{"command": COMMANDS[0], "exit_code": code, "seconds": 1.0, "output_tail": "ok",
                         "junit_xml": None}]}


async def _events(db, run, kind: str) -> list[dict]:
    from sqlalchemy import select

    from app.models import WorkflowRunEvent

    await db.flush()
    rows = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                            WorkflowRunEvent.kind == kind))).scalars().all()
    return [dict(row.detail or {}) for row in sorted(rows, key=lambda row: row.created_at)]


async def _decisions(db, run) -> list[str]:
    return [detail.get("decision") for detail in await _events(db, run, pipeline_head.EVENT)]


@pytest.mark.asyncio
async def test_a_green_pipeline_for_the_pushed_tree_opens_the_pull_request(db, monkeypatch, tmp_path, scm_calls):
    run, session, _admin = await _run(db, monkeypatch)
    await _phase_done(db, session)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    _holds(run, repo, patch, tree)
    assert await pipeline_report.record_report(db, run, _report(run, tree=tree), session_id=session.id) == "green"
    assert run.context["pipeline"]["tree"] == tree and run.context["pipeline"]["device_tree"] == tree
    assert scm_calls == ["push", "pr"] and run.status == "completed"


@pytest.mark.asyncio
async def test_a_change_after_the_green_pipeline_is_not_pushed_until_the_pipeline_ran_on_it(
        db, monkeypatch, tmp_path, scm_calls):
    run, session, _admin = await _run(db, monkeypatch)
    await _phase_done(db, session)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    patch2, tree2 = repo.change({"feature.py": "x = 2\n"})
    _holds(run, repo, patch, tree2)  # the pipeline runs on T, the head that would go out is T2
    assert await pipeline_report.record_report(db, run, _report(run, tree=tree), session_id=session.id) == "green"
    assert scm_calls == [] and run.current_node_id == "pipeline" and run.status != "completed"
    assert pipeline.state(run)["state"] == "pending" and pipeline.state(run)["head_rerun"] is True
    # The re-run on T2 (the change the server now holds) is green for T2: pushed, pull request opened.
    run.context = {**run.context, "device_change": {"base": repo.base, "patch": patch2}}
    assert await pipeline_report.record_report(db, run, _report(run, tree=tree2), session_id=session.id) == "green"
    assert pipeline.state(run)["tree"] == tree2 and scm_calls == ["push", "pr"] and run.status == "completed"


@pytest.mark.asyncio
async def test_a_rerun_that_is_still_on_another_tree_pauses_and_continue_runs_the_pipeline(
        db, monkeypatch, tmp_path, scm_calls):
    from app.services.workflow_runs.actions import available_actions
    from app.services.workflow_runs.pause import continue_run

    run, session, admin = await _run(db, monkeypatch)
    await _phase_done(db, session)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    _patch2, tree2 = repo.change({"feature.py": "x = 2\n"})
    _holds(run, repo, patch, tree2)
    await pipeline_report.record_report(db, run, _report(run, tree=tree), session_id=session.id)  # → re-run
    await pipeline_report.record_report(db, run, _report(run, tree=tree), session_id=session.id)  # still T
    assert scm_calls == [] and run.status == "paused" and run.pause_reason == "pipeline_not_for_head"
    pause = run.node_state["pause"]
    assert pause["pipeline_tree"] == tree and pause["head_tree"] == tree2 and pause["hint"]
    assert sorted(await _decisions(db, run)) == ["paused", "rerun"]
    assert "Run the pipeline again" in [item["label"] for item in await available_actions(db, run, access="write",
                                                                                           user=admin)]
    await continue_run(db, run, user=admin, k=1, is_admin=True)
    assert run.current_node_id == "pipeline" and pipeline.state(run)["state"] == "pending"


@pytest.mark.asyncio
async def test_a_red_pipeline_never_pushes_and_a_session_request_is_refused(db, monkeypatch, tmp_path, scm_calls):
    from app.services.workflow_runs.platform_actions import typed_action

    run, session, _admin = await _run(db, monkeypatch)
    await _phase_done(db, session)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    _holds(run, repo, patch, tree)
    assert await pipeline_report.record_report(db, run, _report(run, code=1, tree=tree), session_id=session.id) == "red"
    assert run.current_node_id == "work" and scm_calls == []
    # A session asking for the push meanwhile (``workflow_action_request``) is refused with the reason.
    outcome, route = await typed_action(db, run, "scm.push", {})
    assert route == "failed" and "red, not green" in outcome.reason and scm_calls == []


@pytest.mark.asyncio
async def test_a_device_tree_that_is_not_the_servers_change_binds_no_tree(db, monkeypatch, tmp_path, scm_calls):
    run, session, _admin = await _run(db, monkeypatch)
    await _phase_done(db, session)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    _holds(run, repo, patch, tree)
    other = "0" * 40
    await pipeline_report.record_report(db, run, _report(run, tree=other), session_id=session.id)
    assert scm_calls == [] and run.current_node_id == "pipeline" and await _decisions(db, run) == ["rerun"]
    events = await _events(db, run, pipeline.EVENT_REPORTED)
    assert events[-1]["tree"] == "" and events[-1]["tree_mismatch"] is True and events[-1]["device_tree"] == other


@pytest.mark.asyncio
async def test_a_workflow_without_a_pipeline_and_a_server_run_push_as_before(db, monkeypatch, tmp_path, scm_calls):
    run, session, _admin = await _run(db, monkeypatch, with_pipeline=False)
    repo = Repo(tmp_path / "copy")
    patch, tree = repo.change({"feature.py": "x = 1\n"})
    _holds(run, repo, patch, tree)
    await _phase_done(db, session)
    assert scm_calls == ["push", "pr"] and run.status == "completed"

    scm_calls.clear()
    run, session, _admin = await _run(db, monkeypatch, runtime="server")  # the pipeline is skipped on the Server
    _holds(run, repo, patch, tree)
    await _phase_done(db, session)
    assert run.context["pipeline"]["state"] == "skipped" and scm_calls == ["push", "pr"]
    assert run.status == "completed"
