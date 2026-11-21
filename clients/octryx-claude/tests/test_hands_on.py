"""The hands-on test on the device: the built app served and used in the installed Chrome.

The two apps below are the regression proof of the feature request "onboarding": one keeps "onboarding done" in
localStorage, the other only in memory, so after a reload the onboarding shows up again and the test is red.
"""

from __future__ import annotations

import json
import shutil

import pytest

from octryx_claude import hands_on
from tests.hands_on_support import IN_MEMORY, PERSISTED, _repo, _view, _why, needs_chrome


@needs_chrome
def test_an_app_that_keeps_its_state_passes_with_screenshots(tmp_path):
    pytest.importorskip("playwright")
    body, shots = hands_on.execute(_view(), _repo(tmp_path, PERSISTED))
    assert body["state"] == "ran", body
    assert [(item["id"], item["passed"]) for item in body["scenarios"]] == [("S1", True), ("S2", True)], \
        _why(body, shots)
    assert "hands-on-s2-beans.png" in body["scenarios"][1]["screenshots"]
    assert (shots / "hands-on-s2-beans.png").is_file()


@needs_chrome
def test_an_onboarding_flag_kept_in_memory_is_red_after_the_reload(tmp_path):
    pytest.importorskip("playwright")
    body, _shots = hands_on.execute(_view(), _repo(tmp_path, IN_MEMORY))
    first = body["scenarios"][0]
    assert body["state"] == "ran" and first["passed"] is False
    assert first["failed_step"] == 5 and "'Welcome to Beans' is shown but must not be" in first["error"]
    assert "hands-on-s1-failed.png" in first["screenshots"]


def test_a_ui_without_serve_is_unavailable_with_the_hint_and_no_ui_is_skipped(tmp_path):
    body, _shots = hands_on.execute(_view(), _repo(tmp_path, PERSISTED, serve=False))
    assert body["state"] == "unavailable" and body["problem"] == hands_on.SERVE_HINT
    assert body["code"] == "serve_missing"  # the platform judges the code, never the text
    shutil.rmtree(tmp_path / "repo")
    body, _shots = hands_on.execute(_view(), _repo(tmp_path, PERSISTED, serve=False, ui=False))
    assert body == {"node_id": "hands_on", "entry": 1, "state": "skipped",
                    "reason": "the environment file declares no UI"}


def test_an_app_that_never_answers_is_unavailable_with_its_output(tmp_path):
    root = _repo(tmp_path, PERSISTED)
    file = root / "web/.octryx/environment.json"
    environment = json.loads(file.read_text())
    environment["serve"] = {"command": "echo build failed; exit 3", "url": "http://127.0.0.1:19/", "ready_seconds": 5}
    file.write_text(json.dumps(environment))
    body, _shots = hands_on.execute(_view(), root)
    assert body["state"] == "unavailable" and "exited" in body["problem"] and "build failed" in body["problem"]


def test_only_a_contract_with_scenarios_is_pending():
    assert hands_on.pending({"hands_on": _view()})["node_id"] == "hands_on"
    assert hands_on.pending({"hands_on": {"scenarios": []}}) is None and hands_on.pending(None) is None
