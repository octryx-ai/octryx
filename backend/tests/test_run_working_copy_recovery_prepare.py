"""The server prepare step, the workspace sweeper, foreign clones, unready candidates, readers and logged connector failures during recovery."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.workflow_runs.workspace.recovery import RECOVERY_KEY
from tests.run_working_copy_recovery_support import (  # noqa: F401
    SECRET,
    _events,
    _git,
    _git_stays_offline,
    _held_run,
    _origin,
    _provider_tool,
    _report,
    _resolution,
    _server_pipeline,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_reader_cannot_run_the_re_prepare(db, tmp_path, monkeypatch):
    import uuid

    from app.models import Project, User
    from app.services.workflow_runs import access
    from app.services.workflow_runs.access import require_run
    from app.services.workflow_runs.records import WorkflowRunError

    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    _admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                     recorded=tmp_path / "gone")
    project = (await db.execute(select(Project).limit(1))).scalar_one()
    run.project_id = project.id
    name = f"reader-{uuid.uuid4().hex[:6]}"
    reader = User(id=str(uuid.uuid4()), username=name, email=f"{name}@example.test", password_hash="x")
    db.add(reader)
    await db.flush()

    async def in_scope(db_, user):  # the reader sees the run's Workspace
        return {project.id}

    monkeypatch.setattr(access, "work_scope_project_ids", in_scope)
    with pytest.raises(WorkflowRunError) as refused:
        await require_run(db, run.id, reader, write=True)  # the run-action route's gate

    assert refused.value.status_code == 403 and calls == [] and RECOVERY_KEY not in run.context


