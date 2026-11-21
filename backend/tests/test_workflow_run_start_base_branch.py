"""A run can start from a named base branch.

Without it, every run branches from the repository's default branch unless an epic chain names the story before it.
A bug reported against an older commit or a story on top of an unmerged one needs to start there; the start's
``base_branch`` is the start point of the run's own branch.
"""

from __future__ import annotations

import pytest

from app.models import WorkflowRun
from tests.test_workflow_run_runtime_target import _device_workspace, _hub, _target  # noqa: F401
from tests.workflow_acceptance_support import systems  # noqa: F401 - the stubbed Jira and GitHub fixture


@pytest.mark.asyncio
@pytest.mark.parametrize(("given", "stored"), [("bench/oe72-base", "bench/oe72-base"), ("  ", None), (None, None)])
async def test_the_start_names_the_base_branch_of_the_runs_own_branch(
        client, auth_headers, db, given, stored, systems):  # noqa: F811
    import subprocess

    _project, item, device = await _device_workspace(db, systems, online=False)
    # The older commit the bug was reported against, as a branch of the remote (the stub serves the bare repository).
    subprocess.run(["git", "-C", str(systems["bare"]), "branch", "bench/oe72-base", "HEAD"], check=True)
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers, json={
        "workflow_key": "bug-fix-reproduction", "work_item_id": item.id, "runtime_target": _target(device),
        **({"base_branch": given} if given is not None else {})})
    assert started.status_code == 200, started.text
    run = await db.get(WorkflowRun, started.json()["run"]["id"])
    await db.refresh(run)
    assert run.context.get("base_branch") == stored  # kept: the start point existed (else base_branch_gone)
