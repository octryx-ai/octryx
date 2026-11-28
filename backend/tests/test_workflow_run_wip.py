"""The run's work in progress: the device's report is kept on the run, and the Server restores it into a
clean working copy when it prepares, never overwriting the copy's own changes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import WorkflowRunEvent
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.workflow_runs.workspace.server_prepare import restore_run_wip
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run, _jobs

pytestmark = pytest.mark.usefixtures("scripted_pool")

SHA = "a" * 40


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


@pytest.mark.asyncio
async def test_the_devices_wip_report_is_kept_on_the_run(db):
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"turn_id": job.turn_id, "kind": "wip_pushed", "state": "pushed",
                                             "branch": f"octryx-wip/{run.id}", "sha": SHA}, limits={})
    assert run.context["wip"]["sha"] == SHA and run.context["wip"]["branch"] == f"octryx-wip/{run.id}"
    await apply_event(db, job, "job_event", {"turn_id": job.turn_id, "kind": "wip_pushed", "state": "pushed",
                                             "branch": "main", "sha": "b" * 40}, limits={})
    assert run.context["wip"]["sha"] == SHA  # a malformed report never replaces the kept WIP
    kinds = [event.kind for event in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id))).scalars()]
    # A failed device push is only a fallback: never an error event (e.g. push_refused).
    assert kinds.count("wip_pushed") == 1 and kinds.count("wip_failed") == 0


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, text=True).stdout.strip()


@pytest.mark.asyncio
async def test_the_server_restores_the_wip_into_a_clean_working_copy(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    remote, dev, server = tmp_path / "remote.git", tmp_path / "dev", tmp_path / "server"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(dev)], check=True)
    (dev / "app.py").write_text("v1\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "base")
    _git(dev, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", str(remote), str(server)], check=True)
    assert (await restore_run_wip(server, "run-1"))["state"] == "absent"

    (dev / "app.py").write_text("v2 wip\n")
    _git(dev, "checkout", "-q", "-b", "octryx-wip/run-1")
    _git(dev, "commit", "-q", "-am", "wip")
    _git(dev, "push", "-q", "origin", "octryx-wip/run-1")
    restored = await restore_run_wip(server, "run-1")
    assert restored["state"] == "restored" and (server / "app.py").read_text() == "v2 wip\n"

    _git(server, "checkout", "-q", "--", ".")  # clean again
    (server / "app.py").write_text("local edit\n")
    assert (await restore_run_wip(server, "run-1"))["state"] == "dirty"
    assert (server / "app.py").read_text() == "local edit\n"


@pytest.mark.asyncio
async def test_the_server_never_restores_a_wip_over_work_the_branch_gained_since(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    remote, dev, server = tmp_path / "remote.git", tmp_path / "dev", tmp_path / "server"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(dev)], check=True)
    (dev / "app.py").write_text("v1\n")
    (dev / "PLAN.md").write_text("plan v1\n")
    _git(dev, "add", "-A")
    _git(dev, "commit", "-q", "-m", "base")
    _git(dev, "push", "-q", "origin", "HEAD:main")
    _git(dev, "checkout", "-q", "-b", "octryx-wip/run-1")
    (dev / "PLAN.md").write_text("plan v2\n")  # the coordinator's turn
    (dev / "app.py").write_text("wip app\n")
    _git(dev, "commit", "-q", "-am", "wip")
    _git(dev, "push", "-q", "origin", "octryx-wip/run-1")
    subprocess.run(["git", "clone", "-q", str(remote), str(server)], check=True)
    (server / "merged.py").write_text("MERGED = True\n")  # an item merged after the WIP was taken
    (server / "app.py").write_text("merged app\n")  # and it changed a file the WIP has too
    _git(server, "add", "-A")
    _git(server, "commit", "-q", "-m", "Merge item api")

    restored = await restore_run_wip(server, "run-1")

    assert restored["state"] == "restored" and restored["files"] == 1, restored
    assert (server / "merged.py").read_text() == "MERGED = True\n"
    assert (server / "app.py").read_text() == "merged app\n"
    assert (server / "PLAN.md").read_text() == "plan v2\n"


def _repos(tmp_path, monkeypatch) -> tuple[Path, Path, str]:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = t\n\temail = t@example.test\n[commit]\n\tgpgsign = false\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    remote, server = tmp_path / "remote.git", tmp_path / "server"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(server)], check=True)
    (server / "app.py").write_text("v1\n")
    _git(server, "add", "-A")
    _git(server, "commit", "-q", "-m", "base")
    _git(server, "push", "-q", "origin", "HEAD:main")
    return remote, server, _git(server, "rev-parse", "HEAD")


PATCH_V2 = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-v1\n+v2 wip\n"
PATCH_NEW = ("diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n"
             "+NEW = 1\n")


@pytest.mark.asyncio
async def test_the_server_pushes_the_wip_from_the_devices_change(tmp_path, monkeypatch):
    from app.services.workflow_runs.server_wip import build_and_push

    remote, server, base = _repos(tmp_path, monkeypatch)
    first = await build_and_push(server, "run-1", base, PATCH_V2, None)
    assert first["state"] == "pushed" and first["branch"] == "octryx-wip/run-1", first
    assert _git(remote, "show", "octryx-wip/run-1:app.py") == "v2 wip"
    assert (server / "app.py").read_text() == "v1\n" and not _git(server, "status", "--porcelain")
    again = await build_and_push(server, "run-1", base, PATCH_V2, None)
    assert (again["state"], again["sha"]) == ("unchanged", first["sha"])
    second = await build_and_push(server, "run-1", base, PATCH_V2 + PATCH_NEW, None)
    assert second["state"] == "pushed" and _git(remote, "rev-parse", "octryx-wip/run-1^") == first["sha"]
    broken = await build_and_push(server, "run-1", base, "--- a/none.py\n+++ b/none.py\n@@ -1 +1 @@\n-x\n+y\n",
                                  None)
    assert (broken["state"], broken["reason"]) == ("failed", "patch_does_not_apply")

    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    restored = await restore_run_wip(other, "run-1")
    assert restored["state"] == "restored" and (other / "new.py").read_text() == "NEW = 1\n"


@pytest.mark.asyncio
async def test_a_failed_device_push_is_replaced_by_the_servers_push(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.workspace import origin_auth

    async def _no_credential(_db, _run, _root):
        return None

    monkeypatch.setattr(origin_auth, "origin_git_env", _no_credential)
    remote, server, base = _repos(tmp_path, monkeypatch)
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    run.context = {**dict(run.context or {}), "local_path": str(server), "base_sha": base,
                   "device_change": {"base": base, "patch": PATCH_V2, "base_unavailable": False, "truncated": False}}
    await apply_event(db, job, "job_event", {"turn_id": job.turn_id, "kind": "wip_failed", "state": "failed",
                                             "branch": f"octryx-wip/{run.id}", "reason": "push_refused"}, limits={})
    events = [(event.kind, event.detail.get("by")) for event in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind.in_(("wip_pushed", "wip_failed"))))).scalars()]
    assert events == [("wip_pushed", "server")]
    assert run.context["wip"]["by"] == "server"
    assert _git(remote, "rev-parse", f"octryx-wip/{run.id}") == run.context["wip"]["sha"]
