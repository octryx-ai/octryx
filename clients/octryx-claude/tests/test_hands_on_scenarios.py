"""The bug flow: the repository's own scenarios, the reproduce check, symptom steps and one pass per serve URL."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octryx_claude import hands_on
from tests.hands_on_support import IN_MEMORY, PERSISTED, _repo, _view, needs_chrome

# ---- the bug flow: the repository's own scenarios and the reproduce check (D) --------------------------

BUG = {"title": "A bean is gone after a reload", "fresh_profile": True, "viewport": {"width": 1280, "height": 800},
       "steps": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Skip"},
                 {"do": "fill", "label": "Bean name", "value": "Bohne 1"}, {"do": "click", "text": "Add bean"},
                 {"do": "reload"}, {"do": "click", "text": "Skip"}, {"do": "expect_text", "text": "Bohne 1"}]}


def _with_bug_file(root: Path, scenario: dict, key: str = "CAF-61") -> None:
    folder = root / "web/tests/hands_on/bugs"
    folder.mkdir(parents=True)
    (folder / f"{key}.json").write_text(json.dumps(scenario))


@needs_chrome
def test_the_reproduce_check_fails_on_the_symptom_and_a_regular_run_keeps_the_scenario(tmp_path):
    pytest.importorskip("playwright")
    root = _repo(tmp_path, IN_MEMORY)  # the onboarding flag in memory: Skip shows again, the bean list is real
    _with_bug_file(root, {**BUG, "steps": [*BUG["steps"][:6], {"do": "expect_text", "text": "Bohne 2"}]})
    view = {**_view(), "mode": "reproduce", "bug_key": "CAF-61", "scenarios": []}
    body, _shots = hands_on.execute(view, root)
    (result,) = body["scenarios"]
    assert body["state"] == "ran" and result["id"] == "repo:tests/hands_on/bugs/CAF-61.json#1"
    assert (result["passed"], result["failed_op"]) == (False, "expect_text")  # the symptom: the right reason
    # Every regular hands-on run also runs the repository's scenarios.
    body, _shots = hands_on.execute(_view(), root)
    ids = [item["id"] for item in body["scenarios"]]
    assert ids == ["S1", "S2", "repo:tests/hands_on/bugs/CAF-61.json#1"] and body["seconds"] >= 0
    assert body["repo_scenarios"] == [{"id": "repo:tests/hands_on/bugs/CAF-61.json#1", "title": BUG["title"]}]


def test_no_bug_scenario_and_a_broken_file_are_reported(tmp_path):
    root = _repo(tmp_path, PERSISTED)
    view = {**_view(), "mode": "reproduce", "bug_key": "CAF-61", "scenarios": []}
    assert hands_on.pending({"hands_on": view}) is not None
    assert hands_on.execute(view, root)[0]["state"] == "no_scenarios"
    from octryx_claude import hands_on_repo

    _with_bug_file(root, {"steps": [{"do": "eval"}]})
    kept, broken = hands_on_repo.load(root / "web", bug_key="CAF-61")
    assert kept == [] and broken[0]["passed"] is False and "not a hands-on scenario file" in broken[0]["error"]


def test_a_repository_scenario_step_is_checked_with_a_message_and_the_obvious_spellings_are_meant(tmp_path):
    import json

    from octryx_claude import hands_on_repo

    bugs = tmp_path / "tests" / "hands_on" / "bugs"
    bugs.mkdir(parents=True)
    (bugs / "OCX-73.json").write_text(json.dumps({"steps": [
        {"do": "goto", "url": "/"}, {"do": "click", "label": "Equipment"}, {"do": "expect_text", "text": "M1"}]}))
    (bugs / "OCX-74.json").write_text(json.dumps({"steps": [{"do": "fill", "label": "Name"}]}))
    scenarios, broken = hands_on_repo.load(tmp_path, bug_key="OCX-73")
    assert broken == [] and scenarios[0]["steps"][:2] == [{"do": "goto", "path": "/"},
                                                          {"do": "click", "text": "Equipment"}]
    _scenarios, broken = hands_on_repo.load(tmp_path, bug_key="OCX-74")
    assert "step 1 (fill) needs label, value; missing value" in broken[0]["error"]


def test_one_hands_on_pass_per_serve_url_on_a_device(tmp_path, monkeypatch):
    import threading

    from octryx_claude import hands_on

    monkeypatch.setattr(hands_on.tempfile, "gettempdir", lambda: str(tmp_path))
    url = "http://127.0.0.1:8090/"
    with hands_on.url_lock(url) as first:
        assert first is True
        seen = []
        other = threading.Thread(target=lambda: seen.append(hands_on.url_lock(url, wait_seconds=0).__enter__()))
        other.start()
        other.join()
        assert seen == [False]
    with hands_on.url_lock(url, wait_seconds=0) as again:
        assert again is True


def test_an_app_that_already_answers_is_never_tested(tmp_path, monkeypatch):
    import http.server
    import threading

    from octryx_claude import hands_on

    root = _repo(tmp_path, PERSISTED)
    url = json.loads((root / "web/.octryx/environment.json").read_text())["serve"]["url"]
    port = int(url.rsplit(":", 1)[1].strip("/"))
    other = http.server.HTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    started = []
    monkeypatch.setattr(hands_on, "start_app", lambda *args: started.append(args) or (None, ""))
    from octryx_claude import serve_port

    # A serve command that does not name its port keeps the declared URL: there the guard refuses.
    monkeypatch.setattr(serve_port, "on_free_port", lambda serve, env, **_kwargs: (serve, env))
    try:
        body, _shots = hands_on.execute(_view(), root)
        monkeypatch.undo()
        monkeypatch.setattr(hands_on, "start_app", lambda *args: started.append(args) or (None, "stop here"))
        moved, _shots = hands_on.execute(_view(), root)  # names it: its own free port, the other app untouched
    finally:
        other.shutdown()
        other.server_close()
    assert body["state"] == "unavailable" and "already answers" in body["problem"]
    [(serve, *_rest)] = started
    assert serve["declared_url"] == url and serve["url"] != url and moved["problem"] == "stop here"


def test_the_symptom_steps_are_the_marked_ones_else_the_closing_expects():
    from octryx_claude.hands_on_browser import symptom_steps

    steps = [{"do": "goto", "path": "/"}, {"do": "expect_text", "text": "M1"}, {"do": "reload"},
             {"do": "screenshot", "name": "after"}, {"do": "expect_no_text", "text": "No grinder yet"},
             {"do": "expect_text", "text": "M1"}]
    assert symptom_steps(steps) == [4, 5]
    assert symptom_steps([*steps[:1], {**steps[1], "symptom": True}, *steps[2:]]) == [1]
    assert symptom_steps(steps[:1]) == []
