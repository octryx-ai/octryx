"""Teamwork on the server (design section 4, "On the server"): a real git repository, one worktree per item.

Two independent items work side by side in their own worktrees and are merged as each ends; a dependent item starts
from the merged HEAD; a conflicting merge is aborted (the working copy stays as it was) and routes ``replan`` with the
files; when every item is merged the working copy is soft-reset to the run's base (one change to push) and the
worktrees go. Each item's turn runs on the runtime target that serves its model, falling back visibly when the
Workspace refuses it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models import Session, WorkflowRunEvent
from app.services.workflow_runs import server_continuation
from app.services.workflow_runs.path_rules import phase_path_outcomes
from app.services.workflow_runs.teamwork import server_items
from tests.teamwork_engine_support import ended_turn, item, items_of, planned_run


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@test", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# Kitchen helper\n")
    _git(path, "init", "-q", "-b", "main")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def turns(monkeypatch):
    """The item turns the executor schedules after the commit: ``(run_id, key, session_id, runtime_target_id)``."""
    scheduled: list[tuple] = []
    monkeypatch.setattr(server_items, "schedule_item_turn",
                        lambda run_id, key, session_id, target, **_: scheduled.append((run_id, key, session_id,
                                                                                        target)))

    async def target_for(db, model):
        return f"rt-{model}" if model else None

    monkeypatch.setattr(server_continuation, "phase_runtime_target_id", target_for)
    return scheduled


def _write(path: Path, relative: str, text: str) -> None:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


async def build(db, run, key: str, files: dict[str, str]) -> None:
    """The item's agent writes its files in its own worktree and ends with done."""
    from app.services.workflow_runs.binding import run_turn_resolution
    from app.services.workflow_runs.phase_outputs import submit_output

    worktree = Path(items_of(run)[key]["path"])
    for relative, text in files.items():
        _write(worktree, relative, text)
    session = await db.get(Session, items_of(run)[key]["session_id"])
    resolution = await run_turn_resolution(db, session, user_message="Build it.")
    assert resolution["workflow_run"].get("item") == key, resolution.get("unmatched_reason")
    await submit_output(db, run, "submit_phase_result", {"value": "done"}, session_id=session.id)
    await ended_turn(db, session.id, resolution, ["edit_workspace_file", "submit_phase_result"])


@pytest.mark.asyncio
async def test_parallel_items_merge_at_once_and_a_dependent_item_starts_from_the_merged_head(db, repo, turns):
    base = _git(repo, "rev-parse", "HEAD")
    run, _session = await planned_run(db, [
        item("api", paths=["server/**"], model="claude-haiku-5-5"),
        item("ui", role="frontend", paths=["web/**"]),
        item("e2e", depends_on=["api", "ui"], paths=["tests/**"])], copy_dir=repo)
    run.branch = "feature/CHEF-1-search"
    run.context = {**run.context, "base_sha": base}
    assert run.current_node_id == "work"
    api, ui = items_of(run)["api"], items_of(run)["ui"]
    assert api["status"] == ui["status"] == "running" and items_of(run)["e2e"]["status"] == "pending"
    assert Path(api["path"]).is_dir() and Path(api["path"]) != Path(ui["path"])
    assert _git(Path(api["path"]), "rev-parse", "--abbrev-ref", "HEAD").endswith("--api")
    # Each item on the runtime target of its own model (ui has none: the thread's runtime).
    assert api["runtime_target_id"] == "rt-claude-haiku-5-5" and ui["runtime_target_id"] is None
    worker = await db.get(Session, api["session_id"])
    assert worker.metadata_["workspace_root"] == api["path"] and worker.origin == "sub_agent"
    # The item writes only its own paths, relative to its own worktree.
    blocked = await phase_path_outcomes(db, worker.id, ["server/search.py", "web/App.tsx"])
    assert [entry["evidence"]["paths"] for entry in blocked] == [["web/App.tsx"]]

    await build(db, run, "api", {"server/search.py": "def search(q):\n    return []\n"})
    assert items_of(run)["api"]["status"] == "merged"
    assert (repo / "server" / "search.py").exists()  # merged into the story's working copy at once
    assert items_of(run)["e2e"]["status"] == "pending"
    await build(db, run, "ui", {"web/App.tsx": "export const App = () => null;\n"})
    e2e = items_of(run)["e2e"]
    assert e2e["status"] == "running"
    assert (Path(e2e["path"]) / "server" / "search.py").exists() and (Path(e2e["path"]) / "web" / "App.tsx").exists()

    await build(db, run, "e2e", {"tests/test_e2e.py": "def test_e2e():\n    assert True\n"})
    assert (run.current_node_id, run.status, run.outcome) == ("done", "completed", "done")
    # One change on the base: the merges are gone from history, everything is staged on base_sha.
    assert _git(repo, "rev-parse", "HEAD") == base
    staged = set(_git(repo, "diff", "--cached", "--name-only").splitlines())
    assert {"server/search.py", "web/App.tsx", "tests/test_e2e.py"} <= staged
    assert not Path(e2e["path"]).exists()  # the worktrees are removed
    keys = [key for _run, key, _session, _target in turns]
    assert sorted(keys[:2]) == ["api", "ui"] and keys[2:] == ["e2e"]  # one turn per item, after the commit


@pytest.mark.asyncio
async def test_a_conflicting_merge_is_aborted_and_routes_replan_with_its_files(db, repo, turns):
    run, _session = await planned_run(db, [item("a", paths=["a/**"]), item("b", paths=["b/**"])], copy_dir=repo)
    await build(db, run, "a", {"README.md": "# Kitchen helper by a\n"})
    head = _git(repo, "rev-parse", "HEAD")
    await build(db, run, "b", {"README.md": "# Kitchen helper by b\n"})
    b = items_of(run)["b"]
    assert (b["status"], b["conflicts"]) == ("conflict", ["README.md"])
    assert _git(repo, "rev-parse", "HEAD") == head and _git(repo, "status", "--porcelain") == ""  # aborted cleanly
    assert run.current_node_id == "plan"
    assert "conflicts in README.md" in run.gate_results["work"]["results"][0]["description"]


class _Factory:
    """A session factory that hands the test's own session to ``run_item_turn``."""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
async def test_the_item_turn_runs_on_its_target_and_falls_back_when_the_model_is_refused(db, repo, turns):
    from app.services.session.turn_refusals import TurnRefusal

    run, _session = await planned_run(db, [item("api", model="claude-haiku-5-5")], copy_dir=repo)
    _run_id, key, session_id, target = turns[0]
    sent: list[str | None] = []

    async def send(_db, *, runtime_target_id, content, **_kwargs):
        sent.append(runtime_target_id)
        assert "Build item 'api'" in content
        return TurnRefusal(state="runtime_not_allowed", detail="not allowed") if runtime_target_id else []

    await server_items.run_item_turn(run.id, key, session_id, target, session_factory=_Factory(db), send=send)
    assert sent == ["rt-claude-haiku-5-5", None]
    refused = [event for event in (await db.execute(
        WorkflowRunEvent.__table__.select().where(WorkflowRunEvent.run_id == run.id))).all()
        if event.kind == "run_turn_model_refused"]
    assert refused and refused[0].detail["item"] == "api"


@pytest.mark.asyncio
async def test_a_failed_platform_turn_retries_the_item_once_in_its_own_session(db, repo, turns):
    run, _session = await planned_run(db, [item("api")], copy_dir=repo)
    session_id = items_of(run)["api"]["session_id"]
    assert await server_items.turn_ended(session_id, failed=True, session_factory=_Factory(db)) is True
    assert (items_of(run)["api"]["status"], items_of(run)["api"]["session_id"]) == ("running", session_id)
    assert [key for _run, key, _session, _target in turns] == ["api", "api"]
    await server_items.turn_ended(session_id, failed=True, session_factory=_Factory(db))
    assert items_of(run)["api"]["status"] == "failed" and run.current_node_id == "plan"
