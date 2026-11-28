from __future__ import annotations

import json
import os
import sys

import httpx
import pytest

from octryx_claude import workspace_prep
from octryx_claude.device_session import SessionRefusedError
from tests.gitrepo import git, requires_git
from tests.test_device_session_parity import BASE, RUN, _of, _prepare, device_state  # noqa: F401
from tests.workspace_prep_support import BRANCH, _contract, _origin, _platform

CHECK = "python -c 'import json'"


SHIM_SETUP = f"mkdir -p .tools && printf '#!/bin/sh\\nexec {sys.executable} \"$@\"\\n' > .tools/octryx-runner && " \
             "chmod +x .tools/octryx-runner"


@requires_git
def test_the_folder_is_checked_out_on_the_runs_branch_created_from_the_remote(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    report = workspace_prep.prepare(_contract(), folder, runtime="device")
    assert report["branch"]["state"] == "checked_out" and report["branch"]["previous"] == "main"
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert (folder / "NOTES.md").read_text() == "branch work\n"
    assert git(folder, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") == f"origin/{BRANCH}"
    assert (report["node_id"], report["entry"]) == ("prepare", 4)
    assert report["environment"]["state"] == "not_declared"
    again = workspace_prep.prepare(_contract(), folder, runtime="device")
    assert again["branch"]["state"] == "already"


@requires_git
def test_foreign_uncommitted_changes_are_never_overwritten(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    (folder / "textkit.py").write_text("def slugify(text):\n    return text.lower()  # local work\n")
    report = workspace_prep.prepare(_contract(), folder, runtime="device")
    assert report["branch"]["state"] == "dirty" and report["branch"]["dirty_files"] == ["textkit.py"]
    assert "environment" not in report
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "local work" in (folder / "textkit.py").read_text()


@requires_git
def test_a_failing_probe_runs_the_declared_setup_in_the_folder(tmp_path, monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    # The runner exists only once the declared setup created it in the folder.
    environment = {"setup": [SHIM_SETUP], "path": [".tools"],
                   "probes": [{"what": "test: octryx-runner -m json", "argv": ["octryx-runner", "-c", "import json"]},
                              {"what": "lint: octryx-runner", "which": "octryx-runner"}]}
    report = workspace_prep.prepare(_contract(environment), folder, runtime="device")
    prepared = report["environment"]
    assert prepared["state"] == "ready", prepared
    assert [step["exit_code"] for step in prepared["setup"]] == [0]
    assert (folder / ".tools" / "octryx-runner").is_file()
    assert git(folder, "status", "--porcelain") == ""  # the environment is no change of the run
    assert "/.tools/" in (folder / ".git" / "info" / "exclude").read_text()
    # Ready now: the next turn runs no setup.
    assert workspace_prep.prepare(_contract(environment), folder, runtime="device")["environment"]["setup"] == []

    outside = {"setup": ["sudo pip install pytest"], "path": [],
               "probes": [{"what": "test: pytest", "which": "pytest-not-here"}]}
    refused = workspace_prep.prepare(_contract(outside), folder, runtime="device")["environment"]
    assert refused["state"] == "not_ready" and refused["setup"][0]["exit_code"] is None
    assert "refused on this device" in refused["setup"][0]["output"]
    assert "pytest-not-here: command not found" in refused["reason"]


@requires_git
def test_a_device_turn_reports_its_preparation_and_starts_only_ready(device_state, tmp_path, monkeypatch):  # noqa: F811
    folder = _origin(tmp_path, monkeypatch)
    environment = {"setup": [SHIM_SETUP], "path": [".tools"],
                   "probes": [{"what": "test: octryx-runner -m json", "argv": ["octryx-runner", "-c", "import json"]}]}
    record: list[httpx.Request] = []
    with _platform(record, ready=True, contract=_contract(environment)) as http:
        prepared = _prepare(device_state, folder, http)
    try:
        report = json.loads(_of(record, "/sessions/workspace-preparation")[0].content)
        assert report["branch"]["state"] == "checked_out" and report["environment"]["state"] == "ready"
        assert report["runtime"] == "device" and report["root"] == os.path.realpath(folder)
        # The preparation happens before the repository binding, which then reports the run's branch.
        paths = [request.url.path.rsplit("/", 1)[-1] for request in record]
        assert paths.index("workspace-preparation") < paths.index("repository")
        assert prepared.env["PATH"].split(os.pathsep)[0] == str((folder / ".tools").resolve())
    finally:
        prepared.close()

    with _platform([], ready=False, contract=_contract(environment)) as http, \
            pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, folder, http)
    assert refused.value.code == "environment_not_ready"
