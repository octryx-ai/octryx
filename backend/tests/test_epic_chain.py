"""An epic works through its stories by itself: the next story starts on the previous branch."""

from __future__ import annotations

import pytest

from app.models import WorkflowRun
from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs import epic_chain
from tests.agent_definition_revision_fixtures import make_project
from tests.phased_workflow_fixtures import admin_user


async def _epic(db):
    admin = await admin_user(db)
    project = await make_project(db)
    epic = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-90", title="Epic", issue_type="epic",
                    project_id=project.id, work_state="intake")
    s1 = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-91", title="S1", epic_key="OCX-90",
                  project_id=project.id, work_state="intake")
    db.add_all([epic, s1])
    await db.flush()
    s2 = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-92", title="S2", epic_key="OCX-90",
                  project_id=project.id, work_state="intake")
    db.add(s2)
    await db.flush()
    return admin, project, epic, s1, s2


def _finished(admin, project, item, workflow_key, outcome="done", branch="feature/OCX-91-s1"):
    return WorkflowRun(project_id=project.id, work_item_id=item.id, workflow_kind="phased", workflow_key=workflow_key, title=item.title,
                       repository="bitbucket:OCX/demo-shop", branch=branch, requested_by=admin.id, status="completed",
                       outcome=outcome, context={})


@pytest.mark.asyncio
async def test_the_spec_starts_the_first_story_and_each_story_the_next_on_its_branch(db, monkeypatch):
    admin, project, epic, s1, s2 = await _epic(db)
    started = []

    async def fake_start(db_, **kwargs):
        run = WorkflowRun(project_id=project.id, work_item_id=kwargs["work_item_id"], workflow_kind="phased", workflow_key=kwargs[
            "workflow_key"], title="x", requested_by=admin.id, status="running", context=kwargs["context"])
        db_.add(run)
        await db_.flush()
        started.append(kwargs)
        return run

    monkeypatch.setattr("app.services.workflow_runs.records.start_run", fake_start)
    spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
    db.add(spec)
    await db.flush()
    first = await epic_chain.continue_epic(db, spec, actor_id=None)
    assert first.work_item_id == s1.id and started[-1]["context"]["base_branch"] == "docs/OCX-90-spec"
    assert started[-1]["workflow_key"] == "epic-delivery"  # the default
    story1 = _finished(admin, project, s1, "epic-delivery")
    db.add(story1)
    await db.flush()
    second = await epic_chain.continue_epic(db, story1, actor_id=None)
    assert second.work_item_id == s2.id and started[-1]["context"]["base_branch"] == "feature/OCX-91-s1"
    story2 = _finished(admin, project, s2, "epic-delivery", branch="feature/OCX-92-s2")
    db.add(story2)
    await db.flush()
    assert await epic_chain.continue_epic(db, story2, actor_id=None) is None  # the epic is through
    assert story2.context["epic_chain"]["state"] == "finished"


def _recording_start(project, admin, started):
    async def fake_start(db_, **kwargs):
        run = WorkflowRun(project_id=project.id, work_item_id=kwargs["work_item_id"], workflow_kind="phased",
                          workflow_key=kwargs["workflow_key"], title="x", requested_by=admin.id, status="running",
                          context=kwargs["context"])
        db_.add(run)
        await db_.flush()
        started.append(kwargs)
        return run
    return fake_start


@pytest.mark.asyncio
async def test_a_spec_that_chose_the_optional_team_delivery_builds_its_stories_with_it(db, monkeypatch):
    """team-delivery ships as an optional workflow, so a spec run that chose it, and a story that ran it, start the
    next story with team-delivery."""
    admin, project, epic, s1, s2 = await _epic(db)
    started = []
    monkeypatch.setattr("app.services.workflow_runs.records.start_run", _recording_start(project, admin, started))
    spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
    spec.context = {"story_workflow": "team-delivery"}
    db.add(spec)
    await db.flush()
    first = await epic_chain.continue_epic(db, spec, actor_id=None)
    assert first.work_item_id == s1.id and started[-1]["workflow_key"] == "team-delivery"
    story1 = _finished(admin, project, s1, "team-delivery")
    db.add(story1)
    await db.flush()
    second = await epic_chain.continue_epic(db, story1, actor_id=None)
    assert second.work_item_id == s2.id and started[-1]["workflow_key"] == "team-delivery"


@pytest.mark.asyncio
async def test_a_spec_run_naming_no_story_workflow_starts_nothing_and_says_so(db, monkeypatch):
    """A typo never builds the epic with the default without a word: the refusal is on the spec run."""
    admin, project, epic, _s1, _s2 = await _epic(db)

    async def never(*_a, **_k):
        raise AssertionError("no start")

    monkeypatch.setattr("app.services.workflow_runs.records.start_run", never)
    spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
    spec.context = {"story_workflow": "team-delivry"}
    db.add(spec)
    await db.flush()
    assert await epic_chain.continue_epic(db, spec, actor_id=None) is None
    assert (spec.context["epic_chain"]["state"], spec.context["epic_chain"]["code"]) == (
        "failed", "not_a_story_workflow")


@pytest.mark.asyncio
async def test_a_story_that_ends_otherwise_starts_nothing(db, monkeypatch):
    admin, project, _epic_item, s1, _s2 = await _epic(db)

    async def never(*_a, **_k):
        raise AssertionError("no start")

    monkeypatch.setattr("app.services.workflow_runs.records.start_run", never)
    for outcome in ("stopped", "blocked"):
        run = _finished(admin, project, s1, "team-delivery", outcome=outcome)
        db.add(run)
        await db.flush()
        assert await epic_chain.continue_epic(db, run, actor_id=None) is None


@pytest.mark.asyncio
async def test_the_next_story_really_starts_and_runs_its_first_node(db):
    """A start inside a savepoint must not stop at the first platform action. A real start of a
    published definition whose first node is a platform action runs on."""
    import copy

    from tests.phased_workflow_fixtures import PHASE, publish_phased

    admin, project, epic, s1, _s2 = await _epic(db)
    definition = {"execution_kind": "phased", "nodes": [
        {"id": "start", "type": "start"},
        {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
        {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
        "edges": [{"id": "a", "source_node_id": "start", "target_node_id": "work"},
                  {"id": "b", "source_node_id": "work", "target_node_id": "done"}]}
    key = await publish_phased(db, definition)
    epic_chain.STORY_WORKFLOW, saved = key, epic_chain.STORY_WORKFLOW
    try:
        spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
        spec.repository = None
        db.add(spec)
        await db.flush()
        child = await epic_chain.continue_epic(db, spec, actor_id=None)
    finally:
        epic_chain.STORY_WORKFLOW = saved
    assert child is not None and child.work_item_id == s1.id and child.current_node_id == "work"
    assert spec.context["epic_chain"]["state"] == "started"


@pytest.mark.asyncio
async def test_a_chained_storys_working_copy_takes_the_remote_branch(tmp_path):
    """A copy started from master while the remote story branch started from the spec gets its push refused as
    non-fast-forward. A chained story's copy takes the remote branch."""
    import subprocess
    from types import SimpleNamespace

    from app.services.workflow_runs.platform.branch_adoption import start_from_adopted

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                              env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "master")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
    git(seed, "checkout", "-q", "-b", "feature/OCX-20-s1")
    (seed / "SPEC.md").write_text("spec\n")
    git(seed, "add", "-A")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "spec")
    git(seed, "checkout", "-q", "master")
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(seed), str(copy))
    git(copy, "checkout", "-q", "-b", "feature/OCX-20-s1")  # what the prepare tool does: from the default branch
    run = SimpleNamespace(context={"base_branch": "docs/OCX-19-spec"})
    assert await start_from_adopted(run, str(copy), "feature/OCX-20-s1") == ""
    assert (copy / "SPEC.md").read_text() == "spec\n"
    assert await start_from_adopted(SimpleNamespace(context={}), str(copy), "feature/OCX-20-s1") == ""  # unchained


@pytest.mark.asyncio
async def test_a_retried_push_of_a_commit_already_on_the_remote_counts_as_pushed(tmp_path):
    """A retried push can find its commit already on the remote branch; "nothing to push" must not end the reviewed
    story blocked. The run's own commit at the remote head is pushed; the bare base is not."""
    import subprocess
    from types import SimpleNamespace

    from app.services.workflow_runs.platform.working_copy_git import _already_pushed

    def git(cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                              capture_output=True, text=True,
                              env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "master")
    git(origin, "commit", "-q", "--allow-empty", "-m", "base")
    git(origin, "checkout", "-q", "-b", "docs/OCX-19-spec")
    git(origin, "commit", "-q", "--allow-empty", "-m", "spec")
    git(origin, "checkout", "-q", "-b", "feature/OCX-20-s1")
    git(origin, "checkout", "-q", "master")
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(origin), str(copy))
    git(copy, "checkout", "-q", "feature/OCX-20-s1")
    run = SimpleNamespace(branch="feature/OCX-20-s1", context={"base_branch": "docs/OCX-19-spec"})
    assert not await _already_pushed(str(copy), run)  # only the spec: nothing of the run's own
    git(copy, "commit", "-q", "--allow-empty", "-m", "OCX-20: S1")
    git(copy, "push", "-q", "origin", "feature/OCX-20-s1")
    assert await _already_pushed(str(copy), run)


def test_the_platforms_commit_says_it_carries_ai_written_work():
    """The story commit is made by the platform, so Claude Code's attribution never applies."""
    from types import SimpleNamespace

    from app.services.workflow_runs.platform.repo_ref import ai_trailers

    run = SimpleNamespace(id="r1", title="S1", ticket_key=None, context={"runtime_target": {"kind": "device", "model": "claude-haiku-5-5"}})
    item = SimpleNamespace(source_key="OCX-20", title="S1", source_type="platform")
    assert ai_trailers(run, item) == "AI-Generated-By-octryx: claude-haiku-5-5\nOctryx-Run: OCX-20"


@pytest.mark.asyncio
async def test_a_restarted_chained_story_adopts_its_branch_holding_only_the_base_commits(db, tmp_path):
    """An aborted run can have created the story branch from the spec branch; the spec commit then counts as foreign
    because the prepare tool's base is the default branch, and a restart ends in branch_conflict. A chained story
    measures its own commits against the story before it."""
    import subprocess

    from app.services.workflow_runs.platform.branch_adoption import existing_branch
    from app.services.workflow_runs.platform.dispatch import ToolOutcome

    def git(cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                              capture_output=True, text=True,
                              env={"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}).stdout

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    git(origin, "commit", "-q", "--allow-empty", "-m", "base")
    git(origin, "checkout", "-q", "-b", "docs/OCX-90-spec")
    git(origin, "commit", "-q", "--allow-empty", "-m", "spec")
    git(origin, "checkout", "-q", "-b", "feature/OCX-91-s1")
    git(origin, "checkout", "-q", "main")
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(origin), str(copy))

    admin, project, _epic_item, s1, _s2 = await _epic(db)
    aborted = _finished(admin, project, s1, "team-delivery", outcome="stopped")
    aborted.status, aborted.context = "stopped", {"branch_created": "feature/OCX-91-s1"}
    restart = _finished(admin, project, s1, "team-delivery")
    restart.status, restart.context = "running", {"base_branch": "docs/OCX-90-spec"}
    db.add_all([aborted, restart])
    await db.flush()
    prepared = ToolOutcome("succeeded", {"local_path": str(copy), "base_branch": "main"})
    outcome = await existing_branch(db, restart, "feature/OCX-91-s1", prepared)
    assert outcome is not None and outcome.ok and outcome.result["status"] == "adopted"
    restart.context = {}  # unchained: the spec commit is not the run's own
    assert not (await existing_branch(db, restart, "feature/OCX-91-s1", prepared)).ok
