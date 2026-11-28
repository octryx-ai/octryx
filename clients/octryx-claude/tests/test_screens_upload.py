from __future__ import annotations

import os
import time
from datetime import UTC
from types import SimpleNamespace

from octryx_claude import screens

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _contract(capability="change"):
    return {"phase": {"capability_class": capability}, "run": {"entry": 3, "current_node": {"id": "implement"}}}


def test_only_recent_images_of_a_changing_phase_are_uploaded_bound_to_the_pass(tmp_path):
    folder = tmp_path / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    (folder / "home.png").write_bytes(PNG)
    (folder / "notes.txt").write_text("x")
    old = folder / "old.png"
    old.write_bytes(PNG)
    stale = time.time() - 2 * screens.RECENT_SECONDS
    os.utime(old, (stale, stale))
    assert screens.pending(_contract("read_only"), tmp_path) == []
    sent = []
    kept = screens.upload(lambda body: sent.append(body) or SimpleNamespace(body={"state": "stored"}),
                          _contract(), tmp_path)
    assert kept == 1 and [body["name"] for body in sent] == ["home.png"]
    assert (sent[0]["node_id"], sent[0]["entry"]) == ("implement", 3)


def test_only_screenshots_written_during_the_pass_count(tmp_path):
    from datetime import datetime

    folder = tmp_path / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    fresh, stale = folder / "s3-home.png", folder / "coming_soon_home.png"
    fresh.write_bytes(PNG)
    stale.write_bytes(PNG)
    entered = time.time() - 600
    os.utime(stale, (entered - 3600, entered - 3600))
    contract = {**_contract(), "run": {"entry": 3, "current_node": {"id": "implement"},
                                       "entered_at": datetime.fromtimestamp(entered, UTC).isoformat()}}
    assert [path.name for path in screens.pending(contract, tmp_path)] == ["s3-home.png"]


def test_the_screenshots_are_those_of_the_last_declared_system_test_run(tmp_path):
    contract = {**_contract(), "phase": {"capability_class": "change",
                                         "system_tests": {"command": ".venv/bin/python -m pytest -v tests/system"}}}
    session = tmp_path / "session"
    session.mkdir()
    assert not screens.note_run(session, contract, {"tool_name": "Bash", "tool_input": {
        "command": ".venv/bin/python -m pytest -v tests/system 2>&1 | tail -5"}})
    assert screens.last_run(session) is None
    assert screens.note_run(session, contract, {"tool_name": "Bash", "tool_input": {
        "command": ".venv/bin/python -m pytest -v tests/system"}})
    started = screens.last_run(session)
    folder = tmp_path / "repo" / "test-reports" / "screenshots"
    folder.mkdir(parents=True)
    (folder / "new.png").write_bytes(PNG)
    old = folder / "before-run.png"
    old.write_bytes(PNG)
    os.utime(old, (started - 60, started - 60))
    assert [path.name for path in screens.pending(contract, tmp_path / "repo", since=started)] == ["new.png"]
