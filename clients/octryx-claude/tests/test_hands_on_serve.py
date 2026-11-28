from __future__ import annotations

import pytest

from octryx_claude import hands_on, hands_on_app
from tests.hands_on_support import PERSISTED, SCENARIOS, _port, _repo, _view, _why, needs_chrome


def test_an_orphaned_serve_group_of_this_device_is_ended_before_the_next_pass(tmp_path, monkeypatch):
    import os
    import time

    from octryx_claude import hands_on

    monkeypatch.setattr(hands_on.tempfile, "gettempdir", lambda: str(tmp_path))
    port = _port()
    serve = {"command": f"python3 -m http.server {port} --bind 127.0.0.1", "url": f"http://127.0.0.1:{port}/",
             "ready_seconds": 30}
    process, problem = hands_on.start_app(serve, tmp_path, dict(os.environ), tmp_path / "serve.log")
    assert problem == "" and hands_on._answers(serve["url"])  # the launcher stops here without stop_app
    assert hands_on.reap_orphan(serve["url"]) is True
    time.sleep(1)
    assert not hands_on._answers(serve["url"]) and process.poll() is not None
    assert hands_on.reap_orphan(serve["url"]) is False  # nothing recorded any more


def test_a_launcher_restarted_while_serve_is_running_ends_the_previous_group_at_start(tmp_path, monkeypatch):
    import os
    import time

    from octryx_claude import hands_on

    monkeypatch.setattr(hands_on.tempfile, "gettempdir", lambda: str(tmp_path))
    port = _port()
    serve = {"command": f"python3 -m http.server {port} --bind 127.0.0.1", "url": f"http://127.0.0.1:{port}/",
             "ready_seconds": 30}
    process, problem = hands_on.start_app(serve, tmp_path, dict(os.environ), tmp_path / "serve.log")
    assert problem == ""  # the serve command starts:
    assert hands_on_app.reap_all() == 1
    time.sleep(1)
    assert not hands_on._answers(serve["url"]) and process.poll() is not None
    assert not list(tmp_path.glob("octryx-hands-on-*.serve.json")) and hands_on_app.reap_all() == 0


def test_a_starting_launcher_never_ends_another_launcher_s_running_app(tmp_path, monkeypatch):
    import os

    from octryx_claude import hands_on

    monkeypatch.setattr(hands_on.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(tmp_path / "running-launcher"))
    port = _port()
    serve = {"command": f"python3 -m http.server {port} --bind 127.0.0.1", "url": f"http://127.0.0.1:{port}/",
             "ready_seconds": 30}
    process, problem = hands_on.start_app(serve, tmp_path, dict(os.environ), tmp_path / "serve.log")
    try:
        assert problem == ""
        assert hands_on_app.reap_all(tmp_path / "other-launcher") == 0  # another launcher starts
        assert hands_on._answers(serve["url"]) and process.poll() is None
        assert hands_on_app.reap_all(tmp_path / "running-launcher") == 1  # its own next start ends it
    finally:
        hands_on.stop_app(process, serve["url"])


def test_an_app_problem_names_its_code():
    assert hands_on.app_problem_code("the app (x) exited on http://127.0.0.1:1/:\nboom") == "app_exited"
    assert hands_on.app_problem_code("the app (x) was killed on http://127.0.0.1:1/:\n") == "app_killed"
    assert hands_on.app_problem_code("the app (x) did not answer on http://127.0.0.1:1/:\n") == "app_not_answering"


def test_how_the_serve_group_ended_is_recorded_and_written_to_its_log(tmp_path):
    import subprocess
    import sys
    import time

    log = tmp_path / "serve.log"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    process.octryx_started, process.octryx_log = time.monotonic(), log
    end = hands_on.stop_app(process)
    assert (end["by"], end["signal"], end["exit_code"]) == ("stop_app", 15, None)
    assert "[octryx] serve group ended:" in log.read_text()
    done = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"], start_new_session=True)
    done.wait()
    assert hands_on.stop_app(done)["by"] == "itself" and hands_on.stop_app(done)["exit_code"] == 3


@needs_chrome
def test_a_restart_waits_for_what_the_app_is_still_writing(tmp_path):
    pytest.importorskip("playwright")
    root = _repo(tmp_path, PERSISTED)
    page = root / "web" / "index.html"
    page.write_text(page.read_text().replace(
        "localStorage.setItem('beans', JSON.stringify([...beans, name])); render();",
        "setTimeout(() => { localStorage.setItem('beans', JSON.stringify([...beans, name])); render(); }, 700);"))
    view = {**_view(), "scenarios": [SCENARIOS[1]]}

    body, shots = hands_on.execute({**view, "restart_settle": {"network_idle_seconds": 0, "storage_ms": 0}}, root)
    assert [item["passed"] for item in body["scenarios"]] == [False], _why(body, shots)  # closed too early: lost
    body, shots = hands_on.execute(view, root)  # the device's default settle
    assert [item["passed"] for item in body["scenarios"]] == [True], _why(body, shots)
