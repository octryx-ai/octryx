"""A runtime binding that drifts during or after the clone is never adopted and routes nothing, and long credential URLs are not recorded."""

from __future__ import annotations

import json

import pytest

from app.services.workflow_runs.runtime_target.switch import change_runtime
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from app.services.workflow_runs.workspace.recovery import EVENT_RECREATED, RECOVERY_KEY
from tests.run_working_copy_recovery_support import (  # noqa: F401
    BRANCH,
    _events,
    _git_stays_offline,
    _held_run,
    _origin,
    _provider_tool,
    _server_pipeline,
)

# --- The whole binding, re-checked before anything is taken over or written --------------------------------------


def _drift(kind: str):
    """A change another request makes to the run while the clone runs."""
    def apply(run) -> None:
        if kind == "runtime":
            run.context = {**dict(run.context or {}),
                           "runtime_target": {"kind": "device", "device_id": "different-device", "folder": "/other"}}
        elif kind == "node":
            run.current_node_id = "done"
        elif kind == "entry":
            run.node_state = {**dict(run.node_state or {}), "entry": int(dict(run.node_state or {}).get("entry")
                                                                           or 0) + 1}
        elif kind == "branch":
            run.branch = f"{BRANCH}-renamed"
    return apply


@pytest.mark.parametrize("kind", ["runtime", "node", "entry", "branch"])
@pytest.mark.asyncio
async def test_a_binding_that_drifts_during_the_clone_adopts_and_writes_nothing(db, tmp_path, monkeypatch, kind):
    origin, _seed, base = _origin(tmp_path)
    box: dict = {}

    async def drifted():
        _drift(kind)(box["run"])
        await db.flush()

    _provider_tool(monkeypatch, origin, during=drifted)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")
    box["run"] = run
    before = dict(run.context[PREPARATION_KEY])

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY not in run.context and run.context["local_path"] == str(tmp_path / "gone")
    assert EVENT_RECREATED not in [event.kind for event in await _events(db, run)]
    assert not list(persistent.rglob("run-copies/*"))
    # The caller wrote no stale server report and paused nothing on the changed binding.
    assert run.context[PREPARATION_KEY] == before
    assert run.status == "running"


@pytest.mark.asyncio
async def test_a_changed_runtime_binding_is_not_adopted_after_clone(db, tmp_path, monkeypatch):
    # Fails without the binding re-check.
    origin, _seed, base = _origin(tmp_path)
    box: dict = {}

    async def changed():
        run = box["run"]
        run.context = {**dict(run.context or {}),
                       "runtime_target": {"kind": "device", "device_id": "different-device", "folder": "/other"}}
        await db.flush()

    _provider_tool(monkeypatch, origin, during=changed)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")
    box["run"] = run
    await change_runtime(db, run, user=admin, raw={"kind": "server"})
    assert RECOVERY_KEY not in run.context, run.context.get(RECOVERY_KEY)
    assert not list(persistent.rglob("run-copies/*"))


@pytest.mark.asyncio
async def test_the_prepare_step_on_a_drifted_binding_routes_nothing(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.platform_actions import WAIT
    from app.services.workflow_runs.workspace.preparation import prepare_workspace

    origin, _seed, base = _origin(tmp_path)
    box: dict = {}

    async def drifted():
        _drift("entry")(box["run"])
        await db.flush()

    _provider_tool(monkeypatch, origin, during=drifted)
    _admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                     recorded=tmp_path / "gone")
    box["run"] = run
    before = dict(run.context[PREPARATION_KEY])
    node = (await graph_for_run(db, run)).nodes[run.current_node_id]

    outcome, route = await prepare_workspace(db, run, node)

    assert route == WAIT and outcome.result.get("superseded") is True
    assert run.context[PREPARATION_KEY] == before and RECOVERY_KEY not in run.context


@pytest.mark.asyncio
async def test_a_long_truncated_credential_url_is_not_recorded(db, tmp_path, monkeypatch):
    # The canary: passes with and without the binding re-check.
    origin, _seed, base = _origin(tmp_path)
    secret = "CANARY-CREDENTIAL-PREFIX-" + "q" * 700
    calls = _provider_tool(monkeypatch, origin, fail=f"clone https://x-token-auth:{secret}@bitbucket.org/x.git failed")
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone")
    await change_runtime(db, run, user=admin, raw={"kind": "server"})
    assert len(calls) == 1, calls
    recorded = json.dumps([run.context, [event.detail for event in await _events(db, run)]], default=str)
    assert "CANARY-CREDENTIAL-PREFIX-" not in recorded
