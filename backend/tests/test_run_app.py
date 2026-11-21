"""A run names the app it works on in a repository that holds several (a record that points at a Flutter app must
not make a Python and a Node bug run `flutter test` with their shells held to the Flutter folder). The start's ``app``
chooses the app; its environment file is the run's from then on (``context.app``), and the record's file stays the
default."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api.routes._workflow_run_http import StartRunRequest, _start_context
from app.models import CodeRepository, Project
from app.services.workflow_runs.pipeline import environment_file_for
from app.services.workflow_runs.workspace import spec
from app.services.workflow_runs.workspace.run_app import run_environment_file
from tests.test_environment_file import VALID, _write

FLUTTER = "coffee/flutter/claude/.octryx/environment.json"


async def _bench(db) -> Project:
    project = Project(name=f"bench-{uuid.uuid4().hex[:6]}", config={})
    db.add(project)
    await db.flush()
    db.add(CodeRepository(project_id=project.id, name="octryx-ai/bench", repo_root="/r", provider="github",
                          config_json={"coding_setup": {"environment_file": FLUTTER}}))
    await db.flush()
    return project


def _run(project: Project, root, app: str | None = None) -> SimpleNamespace:
    body = StartRunRequest(workflow_key="bug-fix-reproduction", **({"app": app} if app is not None else {}))
    return SimpleNamespace(project_id=project.id, repository="github:octryx-ai/bench",
                           context={"local_path": str(root), **(_start_context(body) or {})})


@pytest.mark.asyncio
@pytest.mark.parametrize(("app", "command"), [("e2e/python", "python3 -m pytest -q"), ("e2e/node/", "npm test")])
async def test_the_started_app_is_the_runs_environment_not_the_records(db, tmp_path, app, command):
    project = await _bench(db)
    _write(tmp_path, FLUTTER, {**VALID, "test": "flutter test"})
    _write(tmp_path, f"{app.rstrip('/')}/.octryx/environment.json", {**VALID, "test": command})
    run = _run(project, tmp_path, app)
    environment = await spec.environment_for_run(db, run)
    folder = app.rstrip("/")
    assert (environment["environment_file"], environment["app_folder"], environment["test"]) == (
        f"{folder}/.octryx/environment.json", folder, command)
    assert run.context["app"] == {"path": folder, "environment_file": f"{folder}/.octryx/environment.json",
                                  "source": "start"}
    assert await environment_file_for(db, run) == {"file": f"{folder}/.octryx/environment.json", "app_folder": folder}


@pytest.mark.asyncio
async def test_without_an_app_the_records_file_is_the_runs_and_stays_it(db, tmp_path):
    project = await _bench(db)
    _write(tmp_path, FLUTTER, {**VALID, "test": "flutter test"})
    run = _run(project, tmp_path)
    assert (await spec.environment_for_run(db, run))["test"] == "flutter test"
    assert run.context["app"] == {"path": "coffee/flutter/claude", "environment_file": FLUTTER, "source": "record"}
    record = (await db.execute(CodeRepository.__table__.select().where(
        CodeRepository.project_id == project.id))).first()
    await db.execute(CodeRepository.__table__.update().where(CodeRepository.id == record.id).values(
        config_json={"coding_setup": {"environment_file": "other/.octryx/environment.json"}}))
    assert run_environment_file(run) == FLUTTER  # a record changed mid-run never moves the run's file


@pytest.mark.parametrize("app", ["../outside", "/abs/path", "a\\b", "e2e/../../x"])
def test_an_app_outside_the_repository_is_refused(app):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        _start_context(StartRunRequest(workflow_key="bug-fix-reproduction", app=app))
    assert refused.value.status_code == 422
