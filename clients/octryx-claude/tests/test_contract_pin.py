"""The run's environment file is its contract: with the platform's pin
the launcher runs the pinned file, never the one the agent rewrote in the working tree."""

from __future__ import annotations

import json

from octryx_claude import environment_file, local_tests

FILE = "app/.octryx/environment.json"
PINNED = {"test": "flutter test", "system_test": "python3 system_test/run.py",
          "serve": {"command": "python3 -m http.server 8090", "url": "http://127.0.0.1:8090/"}}


def _repo(tmp_path, environment):
    folder = tmp_path / "app" / ".octryx"
    folder.mkdir(parents=True)
    (folder / "environment.json").write_text(json.dumps(environment))
    return tmp_path


def test_the_pinned_file_wins_over_the_rewritten_one(tmp_path):
    root = _repo(tmp_path, {"test": "true", "system_test": "true"})  # what the agent wrote (sed, redirect, Edit)
    pin = {"file": FILE, "sha256": "a" * 64, "environment": PINNED}
    account = environment_file.resolve(root, FILE, pin)
    assert account["state"] == environment_file.OK and account["pinned"] is True
    assert account["environment"]["test"] == "flutter test" and account["sha256"] == "a" * 64
    assert environment_file.resolve(root, FILE, None)["environment"]["test"] == "true"  # no pin: the tree
    assert environment_file.resolve(root, FILE, {**pin, "file": "other/.octryx/environment.json"})[
        "environment"]["test"] == "true"


def test_only_the_pinned_commands_run_outside_the_sandbox(tmp_path):
    root = str(_repo(tmp_path, {"test": "bash run-anything.sh", "system_test": "true"}))
    pin = {"file": FILE, "sha256": "a" * 64, "environment": PINNED}
    assert local_tests.is_test_run("flutter test", root, pin)
    assert not local_tests.is_test_run("true", root, pin)  # declared only in the rewritten tree
