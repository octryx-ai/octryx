"""A device job without an agent: archives fetched into one temporary folder, the pinned tools run on
them with the placeholders filled, the raw result answered, a cut output file uploaded whole, the folder removed."""

from __future__ import annotations

from pathlib import Path

from octryx_claude import tool_jobs

JOB = "tj_" + "a" * 20


def _fetch(state, item, dest):
    if item["name"] == "broken":
        return None, "the archive does not match its sha256; nothing was unpacked"
    (dest / "pay").mkdir(parents=True)
    (dest / "pay" / "config.py").write_text("KEY = 1\n")
    return Path(dest), ""


def test_the_steps_run_on_the_fetched_archives_and_a_large_report_goes_up_whole():
    seen, uploads = {}, []

    def run(tool, args, *, cwd, timeout, outputs):
        unpacked = (cwd / "files" / "pay" / "config.py").exists()
        seen.update(tool=tool, args=args, cwd=cwd, outputs=outputs, files=unpacked)
        (cwd / "out" / "g.sarif").write_text("x" * 50)
        return {"status": "ok", "exit": 1, "stdout": "", "stderr": "", "truncated": True,
                "files": {"out/g.sarif": "x" * 10}}

    def upload(state, data, *, name):
        uploads.append((name, len(data)))
        return {"id": "up1", "sha256": "s", "bytes": len(data)}

    body = {"job_id": JOB, "archives": [{"name": "files", "url": "/api/v1/devices/archives/x", "sha256": "s"}],
            "steps": [{"id": "secrets", "tool": "gitleaks", "timeout": 30, "outputs": ["g.sarif"],
                       "args": ["dir", "--report-path", "{out:g.sarif}", "{archive:files}"]}]}
    kind, answer = tool_jobs.run_job(None, body, fetch=_fetch, upload=upload, run=run)
    assert kind == "tool_job_result" and seen["files"] and seen["tool"] == "gitleaks"
    assert seen["args"] == ["dir", "--report-path", "out/g.sarif", "files"] and seen["outputs"] == ["out/g.sarif"]
    assert answer["steps"] == [{"id": "secrets", "status": "ok", "exit": 1, "stdout": "", "stderr": "",
                                "truncated": True, "files": {"g.sarif": {"upload": "up1"}}}]
    assert uploads == [("g.sarif", 50)] and not seen["cwd"].exists()  # the folder is gone afterwards


def test_an_archive_that_does_not_check_out_fails_the_job_and_nothing_runs():
    ran = []
    body = {"job_id": JOB, "archives": [{"name": "broken"}], "steps": [{"id": "a", "tool": "gitleaks", "args": []}]}
    kind, answer = tool_jobs.run_job(None, body, fetch=_fetch, run=lambda *a, **k: ran.append(a))
    assert kind == "tool_job_failed" and "sha256" in answer["reason"] and ran == []
