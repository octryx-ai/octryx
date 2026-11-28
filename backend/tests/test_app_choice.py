"""A run in a repository with several apps knows its app before any change."""

from __future__ import annotations

import importlib.util
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import CodeRepository, Project
from app.services.workflow_runs.bugs.intake import intake_check
from app.services.workflow_runs.workspace.app_choice import choose_app
from app.services.workflow_runs.workspace.run_app import (
    APP_KEY,
    APP_SOURCE_START,
    app_context,
    record_apps,
    remember_apps,
    reported_apps,
)

LAUNCHER_APPS = Path(__file__).parents[2] / "clients" / "octryx-claude" / "octryx_claude" / "apps.py"
BENCH = ["coffee/flutter/claude/.octryx/environment.json", "e2e/node/.octryx/environment.json",
         "e2e/python/.octryx/environment.json"]
REPORT = ("Splitbill shares do not add up\n## Steps\npython3 -m splitbill 10.00 3 in e2e/python\n"
          "## Expected\n10.00\n## Actual\n9.99\n## Environment\nmacOS, Python 3.12")


async def _run(db, apps: list[str] | None = None, **context) -> SimpleNamespace:
    project = Project(name=f"bench-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    db.add(CodeRepository(project_id=project.id, name="octryx-ai/bench", repo_root="/r", provider="github",
                          config_json={"coding_setup": {"environment_file": BENCH[0]}}))
    await db.flush()
    run = SimpleNamespace(id=str(uuid.uuid4()), project_id=project.id, repository="github:octryx-ai/bench",
                          context=dict(context), work_item_id=None, title="")
    if apps is not None:
        await remember_apps(db, run, {"apps": apps})
    return run


def test_the_launcher_reports_only_tracked_environment_files(tmp_path):
    spec = importlib.util.spec_from_file_location("launcher_apps", LAUNCHER_APPS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found_apps = module.found_apps

    for folder in ("e2e/python", "e2e/node", "scratch"):
        (tmp_path / folder / ".octryx").mkdir(parents=True)
        (tmp_path / folder / ".octryx" / "environment.json").write_text("{}")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "e2e"], check=True)
    assert found_apps(tmp_path) == ["e2e/node/.octryx/environment.json", "e2e/python/.octryx/environment.json"]
    assert found_apps(tmp_path / "missing") == []


def test_a_reported_path_outside_the_repository_is_dropped():
    assert reported_apps({"apps": ["../x/.octryx/environment.json", "/abs/e.json", BENCH[2], 7]}) == [
        {"path": "e2e/python", "environment_file": BENCH[2]}]


@pytest.mark.asyncio
async def test_the_record_keeps_the_reported_apps(db):
    run = await _run(db, BENCH)
    assert [app["path"] for app in await record_apps(db, run)] == ["coffee/flutter/claude", "e2e/node", "e2e/python"]
    await remember_apps(db, run, {})  # a report without the list keeps it
    assert len(await record_apps(db, run)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(("components", "text", "chosen"), [
    (["e2e/node"], "", "e2e/node"),
    (["node"], "", "e2e/node"),
    ([], "see e2e/python/splitbill/core.py", "e2e/python"),
])
async def test_the_intake_chooses_the_named_app(db, components, text, chosen):
    run = await _run(db, BENCH)
    assert await choose_app(db, run, components=components, text=text) == {}
    assert run.context[APP_KEY] == {**app_context(chosen, "intake")}


@pytest.mark.asyncio
async def test_the_start_wins_and_a_single_app_needs_no_question(db):
    started = await _run(db, BENCH, **{APP_KEY: app_context("e2e/node", APP_SOURCE_START)})
    assert await choose_app(db, started, components=[], text="e2e/python") == {}
    assert started.context[APP_KEY]["path"] == "e2e/node"
    single = await _run(db, BENCH[2:])
    assert await choose_app(db, single, components=[], text="") == {}
    assert single.context[APP_KEY]["path"] == "e2e/python"
    unknown = await _run(db)
    assert await choose_app(db, unknown, components=[], text="") == {} and APP_KEY not in unknown.context


@pytest.mark.asyncio
async def test_an_unnamed_app_is_one_question_and_its_answer_chooses(db):
    run = await _run(db, BENCH)
    run.title = REPORT.replace(" in e2e/python", "")
    _outcome, route = await intake_check(db, run, {})
    assert route == "incomplete"
    assert run.context["bug_report"]["missing"] == ["app"]
    assert run.context["bug_report"]["app_options"] == ["coffee/flutter/claude", "e2e/node", "e2e/python"]
    run.context["po_answers"] = [{"text": "app: e2e/python"}]
    _outcome, route = await intake_check(db, run, {})
    assert route == "succeeded" and run.context[APP_KEY]["path"] == "e2e/python"
