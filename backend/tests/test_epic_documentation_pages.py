"""Unattended epic documentation: the spec page, a feature page per story, the epic overview.

Real paths: the platform actions through the governed Confluence tools (named-connection routing by space, the
connection's allowlist, pinned instance/connection) against the writable Confluence stub, the engine routing the
optional step to ``done``, the seeds.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import Project, WorkItemDocument
from app.services.workflow_runs.documentation.auto_pages import publish_feature, publish_spec
from app.services.workflow_runs.engine import resolve_current_node
from app.services.workflow_runs.graph_validation import validate_phased_definition
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.seeding import phased_seeds
from tests.documentation_acceptance_support import PARENT, SPACE
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.epic_documentation_pages_support import _events, _git, _run, _workspace
from tests.phased_workflow_fixtures import PHASE, publish_phased

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("public_source_dns")]


async def _engine_run(db, admin, project, story):
    definition = {
        "execution_kind": "phased",
        "nodes": [{"id": "start", "type": "start", "label": "Start"},
                  {"id": "work", "type": "phase", "label": "Build", "config": copy.deepcopy(PHASE)},
                  {"id": "docs", "type": "platform_action", "label": "Pages",
                   "config": {"action": "documentation.publish_feature"}},
                  {"id": "done", "type": "outcome", "label": "Done", "config": {"outcome": "done"}}],
        "edges": [{"id": "e1", "source_node_id": "start", "target_node_id": "work"},
                  {"id": "e2", "source_node_id": "work", "target_node_id": "docs"},
                  *({"id": f"e-{when}", "source_node_id": "docs", "target_node_id": "done", "when": when}
                    for when in ("succeeded", "failed", "skipped"))],
    }
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=project.id,
                          session=await new_chat_session(db, admin, project.id))
    run.work_item_id, run.pull_request = story.id, {"id": "8", "url": "https://bitbucket.example.test/pr/8"}
    await db.flush()
    await resolve_current_node(db, run, None, actor_id=None)
    return run


def _seed(key: str) -> dict:
    return copy.deepcopy(next(seed for seed in phased_seeds() if seed["key"] == key)["definition"])


async def test_the_spec_and_each_story_publish_under_the_grant_and_touch_only_their_own_pages(db, monkeypatch,
                                                                                              tmp_path):
    admin, project, stub, epic, (s1, s2) = await _workspace(db, monkeypatch)
    stub.put("950", "Someone else's page", "<p>Human notes.</p>", parent=PARENT)
    _git(tmp_path, "init", "-q")
    (tmp_path / "coffee").mkdir()
    (tmp_path / "coffee" / "SPEC.md").write_text("# Coffee\n\n## 1 Goal\n\nOrder <b>coffee</b>.\n\n- one\n- two\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "spec")
    spec_run = _run(admin, project, epic, "spec-writing", pr="7", context={
        "local_path": str(tmp_path), "head_sha": _git(tmp_path, "rev-parse", "HEAD"),
        "stories": [s1.source_key, s2.source_key]})
    db.add(spec_run)
    await db.flush()

    outcome, route = await publish_spec(db, spec_run, {})
    assert route == "succeeded", outcome.reason
    grant = spec_run.context["documentation_grant"]
    spec_page = grant["pages"]["spec"]
    assert stub.pages[spec_page["page_id"]]["parent"] == PARENT
    body = stub.pages[spec_page["page_id"]]["body"]
    assert "<h3>1 Goal</h3>" in body and "&lt;b&gt;coffee&lt;/b&gt;" in body and "<li>two</li>" in body
    assert (grant["target"]["space_key"], grant["target"]["parent_page_id"], grant["granted_by"]) == (
        SPACE, PARENT, admin.id)
    assert (await _events(db, spec_run, "documentation_page_written"))[0]["operation"] == "created"

    story1 = _run(admin, project, s1, "epic-delivery", after=spec_run, pr="8")
    db.add(story1)
    await db.flush()
    _outcome, route = await publish_feature(db, story1, {})
    assert route == "succeeded"
    pages = story1.context["documentation_grant"]["pages"]
    assert story1.context["documentation_grant"]["id"] == grant["id"]  # inherited through the chain
    feature1, overview = pages[f"feature:{s1.source_key}"], pages["overview"]
    assert {stub.pages[page["page_id"]]["parent"] for page in (feature1, overview)} == {PARENT}
    assert spec_page["url"] in stub.pages[feature1["page_id"]]["body"]  # the feature page links the spec page
    assert "1 of 2 stories" in stub.pages[overview["page_id"]]["body"]

    story2 = _run(admin, project, s2, "epic-delivery", after=story1, pr="9")
    db.add(story2)
    await db.flush()
    _outcome, route = await publish_feature(db, story2, {})
    assert route == "succeeded"
    pages2 = story2.context["documentation_grant"]["pages"]
    assert pages2["overview"]["page_id"] == overview["page_id"] and stub.pages[overview["page_id"]]["version"] == 2
    overview_body = stub.pages[overview["page_id"]]["body"]
    assert "All 2 stories of the epic have a pull request." in overview_body
    assert "https://bitbucket.example.test/pr/8" in overview_body and "https://bitbucket.example.test/pr/9" in (
        overview_body)
    assert stub.pages[feature1["page_id"]]["version"] == 1  # an earlier story's page is not rewritten
    assert (stub.pages["950"]["body"], stub.pages["950"]["version"]) == ("<p>Human notes.</p>", 1)
    assert set(stub.pages) == {PARENT, "950", spec_page["page_id"], feature1["page_id"], overview["page_id"],
                               pages2[f"feature:{s2.source_key}"]["page_id"]}
    rows = (await db.execute(select(WorkItemDocument).where(WorkItemDocument.work_item_id == s2.id))).scalars().all()
    assert [row.page_id for row in rows] == [pages2[f"feature:{s2.source_key}"]["page_id"]]


async def test_a_foreign_page_with_the_storys_title_is_never_overwritten(db, monkeypatch):
    admin, project, stub, _epic, (s1, _s2) = await _workspace(db, monkeypatch)
    stub.put("960", f"{s1.source_key}: {s1.title}", "<p>Written by a person.</p>", parent=PARENT)
    story = _run(admin, project, s1, "epic-delivery", pr="8")
    db.add(story)
    await db.flush()
    _outcome, route = await publish_feature(db, story, {})
    assert route == "succeeded"  # the overview is written; the feature page is skipped
    assert (stub.pages["960"]["body"], stub.pages["960"]["version"]) == ("<p>Written by a person.</p>", 1)
    skipped = await _events(db, story, "documentation_skipped")
    assert skipped[0]["reason"] == "foreign_page" and skipped[0]["page_id"] == "960"
    assert f"feature:{s1.source_key}" not in story.context["documentation_grant"]["pages"]


async def test_a_changed_space_or_parent_after_the_grant_is_skipped_and_nothing_is_written(db, monkeypatch):
    admin, project, stub, _epic, (s1, s2) = await _workspace(db, monkeypatch)
    story1 = _run(admin, project, s1, "epic-delivery", pr="8")
    db.add(story1)
    await db.flush()
    assert (await publish_feature(db, story1, {}))[1] == "succeeded"
    before = {page_id: page["version"] for page_id, page in stub.pages.items()}
    for changed in ({"confluence_space_key": "OTHER"}, {"parent_page_id": "901"}):
        stub.put("901", "Another tree", "<p>x</p>")
        before["901"] = 1
        project = await db.get(Project, project.id)
        project.config = {**project.config, "feature_documentation": {
            "confluence_space_key": SPACE, "parent_page_id": PARENT, "auto_publish": True, **changed}}
        await db.flush()
        story2 = _run(admin, project, s2, "epic-delivery", after=story1, pr="9")
        db.add(story2)
        await db.flush()
        outcome, route = await publish_feature(db, story2, {})
        assert (route, outcome.result["reason"]) == ("skipped", "target_drift"), changed
        assert {page_id: page["version"] for page_id, page in stub.pages.items()} == before


@pytest.mark.parametrize("auto", [False, True])
async def test_without_a_space_or_without_the_opt_in_the_step_is_skipped_and_the_run_is_done(db, monkeypatch, auto):
    admin, project, _stub, _epic, (s1, _s2) = await _workspace(db, monkeypatch, systems=auto, auto=False)
    run = await _engine_run(db, admin, project, s1)
    assert run.outcome == "done"
    assert run.context["actions"]["docs"]["result"] == "skipped"
    reason = "auto_publish_off" if auto else "no_documentation_space"
    assert [event["reason"] for event in await _events(db, run, "documentation_skipped")] == [reason]
    assert "documentation_grant" not in run.context


async def test_a_confluence_error_is_an_event_and_the_run_is_still_done(db, monkeypatch):
    admin, project, stub, _epic, (s1, _s2) = await _workspace(db, monkeypatch)
    stub.writable = False  # Confluence refuses every write
    run = await _engine_run(db, admin, project, s1)
    assert run.outcome == "done"
    assert run.context["actions"]["docs"]["result"] == "failed"
    failures = await _events(db, run, "documentation_failed")
    assert [event["slot"] for event in failures] == [f"feature:{s1.source_key}", "overview"]
    assert set(stub.pages) == {PARENT}


@pytest.mark.parametrize(("key", "action"), [("spec-writing", "documentation.publish_spec"),
                                             ("epic-delivery", "documentation.publish_feature")])
async def test_the_seeds_publish_after_the_pull_request_and_every_result_goes_on_to_done(key, action):
    definition = _seed(key)
    assert validate_phased_definition(definition)["errors"] == []
    docs = next(node for node in definition["nodes"] if node["id"] == "docs")
    assert docs["config"]["action"] == action
    exits = {edge["when"]: edge["target_node_id"] for edge in definition["edges"] if edge["source_node_id"] == "docs"}
    assert exits == {"succeeded": "done", "failed": "done", "skipped": "done"}
    assert next(edge for edge in definition["edges"] if edge["id"] == "e-pr")["target_node_id"] == "docs"
