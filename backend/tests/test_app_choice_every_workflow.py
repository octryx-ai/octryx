"""Every workflow chooses the run's app in its preparation, the same way as the bug intake (a story in a
multi-app repository would otherwise run against the wrong app). A story's component or
description names it; still several, the run pauses ``needs_input`` with the options and a person's answer chooses."""

from __future__ import annotations

import uuid

import pytest

from app.models import CodeRepository, Project
from app.services.workflow_runs.actions import available_actions
from app.services.workflow_runs.records import start_run
from app.services.workflow_runs.workspace.app_choice import paused_for_app
from app.services.workflow_runs.workspace.run_app import APP_KEY, app_context, remember_apps
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.test_workflow_size_class_merge import _definition

APPS = ["coffee/flutter/claude/.octryx/environment.json", "e2e/node/.octryx/environment.json",
        "e2e/python/.octryx/environment.json"]


async def _story_run(db, title: str, **context):
    project = Project(name=f"bench-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    db.add(CodeRepository(project_id=project.id, name="octryx-ai/bench", repo_root="/r", provider="github",
                          config_json={"coding_setup": {"environment_file": APPS[0]}}))
    await db.flush()
    user = await admin_user(db)
    run = await start_run(db, user=user, workflow_key=await publish_phased(db, _definition({})),
                          project_id=project.id, repository="github:octryx-ai/bench")
    run.title, run.context = title, {**dict(run.context or {}), **context}
    await remember_apps(db, run, {"apps": APPS})
    return run, user


@pytest.mark.asyncio
async def test_a_story_whose_description_names_the_app_needs_no_question(db):
    run, _user = await _story_run(db, "Booklist: sort by author\nThe list in e2e/node/src/books.js is unsorted.")
    node = type("Node", (), {"id": "prepare"})()
    assert await paused_for_app(db, run, node) is False
    assert run.context[APP_KEY] == app_context("e2e/node", "intake")


@pytest.mark.asyncio
async def test_a_story_naming_no_app_pauses_for_it_and_the_answer_chooses(db):
    run, user = await _story_run(db, "Make the list sortable")
    node = type("Node", (), {"id": "prepare"})()
    assert await paused_for_app(db, run, node) is True
    assert (run.status, run.pause_reason) == ("paused", "needs_input")
    pause = run.node_state["pause"]
    assert pause["app_options"] == ["coffee/flutter/claude", "e2e/node", "e2e/python"]
    assert pause["resume"] == {"kind": "restart", "node_id": "prepare"} and "e2e/node" in pause["message"]
    actions = await available_actions(db, run, access="write", user=user)
    answer = next(action for action in actions if action["key"] == "continue")
    assert answer["input"]["required"] is True and "e2e/python" in answer["input"]["label"]
    run.context = {**run.context, "po_answers": [{"text": "e2e/python"}]}
    assert await paused_for_app(db, run, node) is False
    assert run.context[APP_KEY]["path"] == "e2e/python"


@pytest.mark.asyncio
async def test_a_bug_whose_intake_chose_the_app_prepares_without_asking_again(db):
    run, _user = await _story_run(db, "Shares do not add up", **{APP_KEY: app_context("e2e/python", "intake")})
    assert await paused_for_app(db, run, type("Node", (), {"id": "prepare"})()) is False
    assert run.status != "paused" and run.context[APP_KEY]["path"] == "e2e/python"
