"""A run's server working copy that is gone is re-created (working-copy recovery).

A copy under ``/tmp/octryx-session-workspaces/…`` can vanish with a recreated API container; without recovery no
action re-creates it and every phase stays held. "Change where the run
executes" → Server (and the server Prepare step) re-clone a recorded-but-missing copy through the governed prepare
tool, into a fresh run-owned folder under the configured (persistent) base, on the run's remote branch at the head the
run knows, verified against its base — and the held phase runs again at the same node and entry. Limits:
no recovery after a change phase (local work may be lost), remote branch missing or moved → refused, a
foreign folder is never overwritten, a run that changed meanwhile adopts nothing, a repeat does not clone again.

Real paths: the run action (``change_runtime``), the governed ``dispatch_tool`` (connector visibility and tool policy
included) and the turn resolution. Only the provider tool's ``execute`` is replaced by a clone from a local bare
origin (no network, no credential); it answers with a credential-bearing URL that must never be recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflow_runs.phase_workspace import LOST_WORKING_COPY_REASON
from app.services.workflow_runs.records import record_event
from app.services.workflow_runs.runtime_target.switch import change_runtime
from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY as PREPARATION_KEY
from app.services.workflow_runs.workspace.recovery import EVENT_RECREATED, RECOVERY_KEY
from tests.run_working_copy_recovery_support import (  # noqa: F401
    BRANCH,
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


def _push_foreign_commit(seed: Path) -> str:
    _git(seed, "checkout", "-qB", BRANCH)
    (seed / "foreign.txt").write_text("not the run's\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "foreign")
    _git(seed, "push", "-q", "origin", BRANCH)
    return _git(seed, "rev-parse", "HEAD")


@pytest.mark.asyncio
async def test_change_runtime_to_server_recreates_a_missing_copy_and_unholds_the_phase(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    recorded = tmp_path / "old-tmp" / "session" / "var/repos/bitbucket/demo-team/test"  # gone with the container
    admin, run, held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base, recorded=recorded)
    assert (held["status"], held["unmatched_reason"]) == ("held", LOST_WORKING_COPY_REASON)
    stands = (run.id, run.current_node_id, dict(run.node_state or {}).get("entry"), run.branch, run.work_item_id)

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    root = Path(run.context["local_path"])
    assert persistent.resolve() in root.parents  # under the configured persistent base, not the stale root
    assert calls and calls[0]["params"]["branch_name"] == BRANCH  # the run's branch: never a second one
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert _git(root, "rev-parse", "HEAD") == base
    assert (root / "tests" / "test_textkit.py").exists()  # the run's base content (the slugify tests) is there
    recovery = run.context[RECOVERY_KEY]
    assert (recovery["head"], recovery["base_sha"], recovery["base_is_ancestor"]) == (base, base, True)
    assert recovery["previous_path"] == str(recorded)
    assert run.context[PREPARATION_KEY]["state"] == "ready"
    assert run.status == "running"
    assert (run.id, run.current_node_id, dict(run.node_state or {}).get("entry"), run.branch,
            run.work_item_id) == stands  # same run, node, entry, branch and Work item
    assert EVENT_RECREATED in [event.kind for event in await _events(db, run)]
    resolution = await _resolution(db, run)
    assert resolution["status"] == "matched"  # the phase is no longer held
    assert resolution["workflow_contract"]["capability_class"] == "read_only"  # the agent gains no change rights

    await change_runtime(db, run, user=admin, raw={"kind": "server"})  # a repeat re-prepare
    assert len(calls) == 1 and Path(run.context["local_path"]) == root  # no second clone


@pytest.mark.asyncio
async def test_no_credential_reaches_the_run_record(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY in run.context  # the clone ran (the tool answered with the credential-bearing URL)
    recorded = json.dumps([run.context, [event.detail for event in await _events(db, run)]], default=str)
    assert SECRET not in recorded and "x-token-auth" not in recorded


@pytest.mark.asyncio
async def test_a_connector_failure_with_a_secret_is_scrubbed_and_nothing_adopted(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin, fail=f"git clone https://x-token-auth:{SECRET}@bitbucket.org/x.git failed")
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY not in run.context and run.context["local_path"] == str(tmp_path / "gone")
    assert SECRET not in json.dumps(run.context, default=str)
    assert not list(persistent.rglob("run-copies/*"))  # the fresh clone folder was removed
    assert (await _resolution(db, run))["status"] == "held"


@pytest.mark.asyncio
async def test_a_non_empty_foreign_folder_at_the_recorded_path_is_never_overwritten(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("someone's files\n")
    admin, run, held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base, recorded=foreign)
    assert held["status"] == "held"  # a plain folder is never taken for the run's copy

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert calls == []  # nothing cloned
    assert (foreign / "notes.txt").read_text() == "someone's files\n"
    assert run.context["local_path"] == str(foreign) and RECOVERY_KEY not in run.context
    assert _report(run)["state"] == "refused" and "never overwritten" in _report(run)["detail"]


@pytest.mark.asyncio
async def test_after_a_change_phase_local_work_may_be_lost_so_nothing_is_recloned(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    calls = _provider_tool(monkeypatch, origin)
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                    recorded=tmp_path / "gone", capability_class="change")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert calls == []
    assert _report(run)["state"] == "recovery_unverified" and "a person decides" in _report(run)["detail"]
    assert RECOVERY_KEY not in run.context


@pytest.mark.asyncio
async def test_a_remote_branch_that_moved_or_is_missing_is_refused(db, tmp_path, monkeypatch):
    origin, seed, base = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    moved = _push_foreign_commit(seed)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert _report(run)["state"] == "recovery_unverified" and moved[:12] in _report(run)["detail"]
    assert RECOVERY_KEY not in run.context and not list(persistent.rglob("run-copies/*"))

    missing_origin, _seed2, missing_base = _origin(tmp_path / "second", branch=False)
    _provider_tool(monkeypatch, missing_origin)
    admin, run, _held, _persistent = await _held_run(db, tmp_path / "second", monkeypatch, base_sha=missing_base,
                                                    recorded=tmp_path / "gone2")
    await change_runtime(db, run, user=admin, raw={"kind": "server"})
    assert "does not exist on the remote" in _report(run)["detail"] and RECOVERY_KEY not in run.context


@pytest.mark.asyncio
async def test_a_head_that_does_not_descend_from_the_base_is_refused(db, tmp_path, monkeypatch):
    origin, _seed, head = _origin(tmp_path)
    _provider_tool(monkeypatch, origin)
    unrelated = "0123456789abcdef0123456789abcdef01234567"
    admin, run, _held, _persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=unrelated, head_sha=head,
                                                    recorded=tmp_path / "gone")

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY not in run.context and run.context["local_path"] == str(tmp_path / "gone")
    assert "does not descend from the run's base" in _report(run)["detail"]
    assert (await _resolution(db, run))["status"] == "held"


@pytest.mark.asyncio
async def test_a_run_that_changed_during_the_clone_adopts_nothing(db, tmp_path, monkeypatch):
    origin, _seed, base = _origin(tmp_path)
    box: dict = {}

    async def stopped_meanwhile():  # another request stops the run while the clone runs
        run = box["run"]
        run.status = "stopped"
        record_event(db, run, "stopped", node_id=run.current_node_id)
        await db.flush()

    _provider_tool(monkeypatch, origin, during=stopped_meanwhile)
    admin, run, _held, persistent = await _held_run(db, tmp_path, monkeypatch, base_sha=base,
                                                   recorded=tmp_path / "gone")
    box["run"] = run
    before = dict(run.context[PREPARATION_KEY])

    await change_runtime(db, run, user=admin, raw={"kind": "server"})

    assert RECOVERY_KEY not in run.context and run.context["local_path"] == str(tmp_path / "gone")
    # Nothing is written on the stopped run: no copy, no ready/not-ready report, no pause.
    assert run.context[PREPARATION_KEY] == before and run.status == "stopped"
    assert not list(persistent.rglob("run-copies/*"))
