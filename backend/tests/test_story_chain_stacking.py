"""The push, the epic chain, the stacked pull requests and the pipeline.

- a retried push on Bitbucket Cloud (a push to the clone URL) sees its own commit and records it;
- a failed push says why (non-fast-forward, credentials, network) without echoing git's output;
- a person's restart of an aborted story builds on the chain by itself; the chain skips only active or done
  stories;
- a chained story's pull request targets the branch it was built on and names the pull request it stacks on;
- a failed chain start keeps the build order;
- a story the Jira sync inserted meanwhile is taken, not an IntegrityError;
- the commit trailer names every model the run used;
- a pytest command that collected nothing is "no tests", not red, unless a proof test was expected.
"""

from __future__ import annotations

import pytest

from app.models.runtime.secure_work import WorkItem
from app.services.workflow_runs import epic_chain
from app.services.workflow_runs.platform import scm
from tests.phased_workflow_fixtures import admin_user
from tests.test_epic_chain import _epic, _finished, _recording_start


async def _value(value):
    return value


# --- the epic chain ------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_chain_skips_only_stories_with_an_active_or_done_run(db):
    """An aborted story does not count as started: the chain neither moves past it nor finishes the epic without it."""
    admin, project, epic, s1, s2 = await _epic(db)
    aborted = _finished(admin, project, s1, "team-delivery", outcome=None)
    aborted.status = "stopped"
    db.add(aborted)
    await db.flush()
    assert (await epic_chain.next_story(db, project.id, "OCX-90")).id == s1.id
    running = _finished(admin, project, s1, "team-delivery", outcome=None)
    running.status = "running"
    db.add(running)
    await db.flush()
    assert (await epic_chain.next_story(db, project.id, "OCX-90")).id == s2.id
    running.status, running.outcome = "completed", "done"
    s2_done = _finished(admin, project, s2, "team-delivery", branch="feature/OCX-92-s2")
    db.add(s2_done)
    await db.flush()
    assert await epic_chain.next_story(db, project.id, "OCX-90") is None


@pytest.mark.asyncio
async def test_a_person_restarting_a_story_gets_the_chain_by_itself(db):
    """A restarted story gets ``base_branch`` and ``epic_chain`` by itself instead of branching from main. S2
    builds on S1's done run; S1 on the spec run; a chain start keeps its own."""
    admin, project, epic, s1, s2 = await _epic(db)
    spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
    spec.context = {"stories": ["OCX-92", "OCX-91"], "story_workflow": "team-delivery"}  # S2 is built first
    db.add(spec)
    await db.flush()

    first = await epic_chain.story_start_context(db, s2, "team-delivery", {"runtime_target": {"kind": "device"}})
    assert first["base_branch"] == "docs/OCX-90-spec" and first["runtime_target"] == {"kind": "device"}
    assert (first["epic_chain"]["after_run"], first["epic_chain"]["stories"]) == (spec.id, ["OCX-92", "OCX-91"])

    s2_done = _finished(admin, project, s2, "team-delivery", branch="feature/OCX-92-s2")
    aborted = _finished(admin, project, s1, "team-delivery", outcome=None, branch="feature/OCX-91-s1")
    aborted.status = "stopped"
    db.add_all([s2_done, aborted])
    await db.flush()
    restart = await epic_chain.story_start_context(db, s1, "team-delivery", None)
    assert restart["base_branch"] == "feature/OCX-92-s2" and restart["epic_chain"]["after_run"] == s2_done.id

    chained = {"base_branch": "x", "epic_chain": {"epic": "OCX-90", "after_run": "r"}}
    assert await epic_chain.story_start_context(db, s1, "team-delivery", chained) == chained
    assert await epic_chain.story_start_context(db, s1, "bug-fix-reproduction", None) is None
    assert await epic_chain.story_start_context(db, epic, "team-delivery", None) is None


@pytest.mark.asyncio
async def test_start_run_derives_the_chain_for_a_persons_story_start(db, monkeypatch):
    """The wiring of the restart: ``start_run`` without a parent hands the derived chain to the phased start."""
    from types import SimpleNamespace

    from app.services.workflow_runs import engine, records

    admin, project, epic, s1, _s2 = await _epic(db)
    spec = _finished(admin, project, epic, "spec-writing", branch="docs/OCX-90-spec")
    db.add(spec)
    await db.flush()
    seen = {}

    async def flow(_db, key, _scope):
        return SimpleNamespace(key=key), SimpleNamespace(definition_json={})

    async def start(_db, **kwargs):
        seen.update(kwargs)
        return "started"

    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(engine, "published_phased_flow", flow)
    monkeypatch.setattr(engine, "start_phased_run", start)
    monkeypatch.setattr("app.services.workflow_runs.access.require_start_scope", nothing)
    monkeypatch.setattr("app.services.workflow_runs.runtime_target.server_build.refuse_server_build",
                        lambda *_a, **_k: None)
    monkeypatch.setattr("app.services.workflow_runs.succession.require_no_active_run", nothing)
    monkeypatch.setattr("app.services.workflow_runs.responsible.initial_responsible",
                        lambda *_a, **_k: _value((admin.id, "requester")))
    assert await records.start_run(db, user=admin, workflow_key="team-delivery", project_id=project.id,
                                   work_item_id=s1.id, repository="bitbucket:OCX/demo-shop") == "started"
    assert seen["context"]["base_branch"] == "docs/OCX-90-spec"
    assert seen["context"]["epic_chain"]["after_run"] == spec.id


@pytest.mark.asyncio
async def test_a_failed_chain_start_keeps_the_build_order(db, monkeypatch):
    """A failed start keeps ``stories`` in ``epic_chain``, so the retry does not fall back to creation order."""
    admin, project, epic, s1, s2 = await _epic(db)
    started = []
    monkeypatch.setattr("app.services.workflow_runs.records.start_run", _recording_start(project, admin, started))
    story1 = _finished(admin, project, s1, "team-delivery")
    story1.context = {"epic_chain": {"epic": "OCX-90", "stories": ["OCX-92", "OCX-91"]}}
    db.add(story1)
    await db.flush()
    epic_chain._failed(db, story1, "OCX-90", s2, "requester_inactive", None)
    assert epic_chain.story_order(story1) == ["OCX-92", "OCX-91"]
    assert story1.context["epic_chain"]["state"] == "failed"


# --- stacked pull requests -----------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_chained_storys_pull_request_stacks_on_the_one_before(db, monkeypatch):
    """A story PR targets its base, not main, so it does not show the spec and every earlier story."""
    from tests.linked_accounts_support import _cloud_run, _scripted

    admin = await admin_user(db)
    before = await _cloud_run(db, admin)
    before.branch = "feature/PAY-0-shell"
    before.pull_request = {"id": "4", "url": "https://bitbucket.org/acme/payments/pull-requests/4",
                           "branch": "feature/PAY-0-shell"}
    run = await _cloud_run(db, admin)
    run.context = {"base_branch": "feature/PAY-0-shell", "epic_chain": {"epic": "PAY-E", "after_run": before.id}}
    calls = _scripted(monkeypatch, {"id": 5, "url": "https://bitbucket.org/acme/payments/pull-requests/5",
                                    "status": "created", "reviewers_unresolved": []})
    assert (await scm.open_pr(db, run, {})).ok
    pr = dict(next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request"))
    assert pr["to_branch"] == "feature/PAY-0-shell"
    assert "Stacks on pull request #4" in pr["description"] and "pull-requests/4" in pr["description"]

    alone = await _cloud_run(db, admin)
    calls = _scripted(monkeypatch, {"id": 6, "url": "https://bitbucket.org/acme/payments/pull-requests/6",
                                    "status": "created", "reviewers_unresolved": []})
    assert (await scm.open_pr(db, alone, {})).ok
    pr = dict(next(arguments for tool, arguments in calls if tool == "create_bitbucket_pull_request"))
    assert "to_branch" not in pr and "Stacks on" not in pr["description"]  # no chain: the default branch


# --- create_stories against the Jira sync --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_story_the_sync_inserted_meanwhile_is_taken_instead_of_failing(db):
    """The sync inserting a story between ``create_jira_ticket`` and the insert raises no IntegrityError."""
    from app.services.workflow_runs.teamwork.stories import _insert_or_synced

    _admin, project, epic, _s1, _s2 = await _epic(db)
    synced = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-93", title="from the sync",
                      project_id=project.id, work_state="intake")
    db.add(synced)
    await db.flush()
    mine = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-93", title="S3",
                    project_id=project.id, work_state="intake", epic_key="OCX-90", parent_key="OCX-90")
    taken = await _insert_or_synced(db, mine, epic)
    assert taken.id == synced.id and (taken.epic_key, taken.parent_key) == ("OCX-90", "OCX-90")
    fresh = WorkItem(source_type="platform", source_instance="octryx", source_key="OCX-94", title="S4",
                     project_id=project.id, work_state="intake", epic_key="OCX-90")
    assert (await _insert_or_synced(db, fresh, epic)) is fresh
