"""Device jobs without an agent (the review bot's scan and the check proof): stored by any process, claimed
by one connected candidate that has the tools, answered raw, judged by the platform; a job nobody runs times out.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceToolJob, DeviceToolJobArchive
from app.services.devices import tool_jobs, tree_archive
from tests.devices.device_support import device_with_grant, user_named


class _Connection:
    def __init__(self, device_id: str, tools: dict) -> None:
        self.device_id, self.tools, self.sent = device_id, tools, []

    async def send(self, message_type: str, body: dict) -> None:
        self.sent.append((message_type, body))


STEPS = [{"id": "secrets", "tool": "gitleaks", "outputs": ["g.sarif"], "timeout": 60,
          "args": ["dir", "--report-path", "{out:g.sarif}", "{archive:files}"]}]


async def _job(db, candidates, **changes):
    archive = tree_archive.build_archive([("pay/config.py", b"KEY = 1\n")], name="files")
    values = {"purpose": "pr_review.scan", "candidates": candidates, "archives": [archive], "steps": STEPS}
    return await tool_jobs.offer(db, **{**values, **changes})


async def test_a_job_goes_to_one_connected_candidate_with_the_tools_and_its_answer_is_kept(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OCTRYX_DEVICE_ARCHIVE_DIR", str(tmp_path))
    user = await user_named(db, "rev")
    first, _ = await device_with_grant(db, user, name="Mac")
    second, _ = await device_with_grant(db, user, name="Linux")
    assert await tool_jobs.devices_of(db, [user.id]) == [first.id, second.id]
    job = await _job(db, [first.id, second.id])
    assert job.needs == ["gitleaks"] and await tool_jobs.result(db, job.id) is None
    assert (await _job(db, ["elsewhere"], needs=[])).needs == []  # a job that runs with what the device has
    stranger, without, mac = (_Connection("other", {"gitleaks": "8.30.1"}), _Connection(second.id, {"gitleaks": None}),
                              _Connection(first.id, {"gitleaks": "8.30.1"}))
    assert [await tool_jobs.deliver(db, connection) for connection in (stranger, without, mac, mac)] == [0, 0, 1, 0]
    (kind, body), = mac.sent
    assert kind == "tool_job" and body["steps"] == job.steps and body["archives"][0]["name"] == "files"
    ident = body["archives"][0]["url"].rsplit("/", 1)[-1]
    assert tree_archive.fetch(ident, first.id) is not None and tree_archive.fetch(ident, second.id) is None
    # Another device's answer, an undeclared step and an undeclared file are ignored; a large file came as upload.
    assert not await tool_jobs.apply_message(db, second.id, "tool_job_result", {"job_id": job.id, "steps": []})
    upload = tree_archive.accept_upload(b'{"runs": []}', device_id=first.id, name="g.sarif")
    assert await tool_jobs.apply_message(db, first.id, "tool_job_result", {"job_id": job.id, "steps": [
        {"id": "secrets", "status": "ok", "exit": 0, "stdout": "x" * 9000, "files": {
            "g.sarif": {"upload": upload["id"]}, "other": "no"}}, {"id": "nope", "status": "ok"}]})
    done = await tool_jobs.result(db, job.id)
    assert done["state"] == "done" and done["device_id"] == first.id
    (step,) = done["steps"]
    assert step["files"] == {"g.sarif": '{"runs": []}'} and len(step["stdout"]) == tool_jobs.TAIL
    assert not await tool_jobs.apply_message(db, first.id, "tool_job_failed", {"job_id": job.id})  # ended once
    assert (await db.execute(select(DeviceToolJobArchive).where(DeviceToolJobArchive.job_id == job.id))).first() is None


async def test_a_job_nobody_takes_times_out_and_on_done_runs_once(db, monkeypatch):
    calls = []

    async def done(db_, job):
        calls.append((job.id, job.state, job.reason))

    import sys
    import types

    probe = types.ModuleType("app.services.tool_jobs_probe")
    probe.done = done
    monkeypatch.setitem(sys.modules, "app.services.tool_jobs_probe", probe)
    job = await _job(db, ["absent"], on_done="tool_jobs_probe:done", timeout_seconds=30)
    job.created_at = job.created_at - timedelta(minutes=5)
    await db.flush()
    assert (await tool_jobs.result(db, job.id))["state"] == "timeout"
    assert await tool_jobs.expire(db) == 0
    assert calls == [(job.id, "timeout", "no candidate device with the tools was connected")]
    assert (await db.get(DeviceToolJob, job.id)).state == "timeout"


@pytest.mark.parametrize(("steps", "why"), [
    ([{"id": "a", "tool": "gitleaks", "args": ["{archive:nope}"]}], "names no archive"),
    ([{"id": "a", "tool": "gitleaks", "args": ["{out:x.sarif}"]}], "names no archive or declared output"),
    ([{"id": "a", "tool": "gitleaks", "args": ["x"], "outputs": ["../x"]}], "plain file name"),
    ([{"id": "a", "tool": "gitleaks", "args": "x"}], "list of strings"),
    ([], "1 to"),
])
async def test_a_job_that_could_never_run_is_refused(db, steps, why):
    with pytest.raises(tool_jobs.ToolJobError, match=why):
        await _job(db, ["d"], steps=steps)
