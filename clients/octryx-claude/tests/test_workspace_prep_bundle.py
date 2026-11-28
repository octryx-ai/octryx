from __future__ import annotations

import json
from pathlib import Path

import httpx

from octryx_claude import workspace_branch, workspace_prep
from tests.gitrepo import git, requires_git
from tests.test_device_session_parity import BASE, RUN, _of, _prepare, device_state  # noqa: F401
from tests.workspace_prep_support import BRANCH, _contract, _no_origin_access, _origin, _platform

# --- The next story's commit is only on origin and the platform's copy ---------------------------


def _bundle_from(server: Path, branch: str, asked: list[list[str]]):
    import base64
    import subprocess

    def source(have: list[str]) -> dict:
        asked.append(have)
        known = [sha for sha in have if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=server,
                                                       capture_output=True).returncode == 0]
        target = server.parent / "out.bundle"
        git(server, "bundle", "create", "-q", str(target), f"refs/heads/{branch}", *[f"^{sha}" for sha in known])
        return {"state": "ready", "ref": f"refs/heads/{branch}", "bundle": base64.b64encode(target.read_bytes())
                .decode()}

    return source


@requires_git
def test_without_origin_access_the_branch_comes_from_the_platforms_bundle(device_state, tmp_path,  # noqa: F811
                                                                          monkeypatch):
    folder = _origin(tmp_path, monkeypatch)
    server = tmp_path / "server"
    git(tmp_path, "clone", "-q", "--branch", BRANCH, str(tmp_path / "origin.git"), str(server))
    (server / "story.py").write_text("# the previous story's commit, pushed from the platform's copy\n")
    git(server, "add", "-A")
    git(server, "commit", "-q", "-m", "previous story")
    head = git(server, "rev-parse", "HEAD")
    _no_origin_access(folder, tmp_path)
    contract = _contract()
    contract["preparation"]["head"] = head
    asked: list[list[str]] = []
    record: list[httpx.Request] = []
    source = _bundle_from(server, BRANCH, asked)
    platform = _platform(record, ready=True, contract=contract)
    original = platform._transport.handle_request

    def with_bundle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions/branch-bundle"):
            record.append(request)
            return httpx.Response(200, json=source(json.loads(request.content)["have"]))
        return original(request)

    platform._transport.handle_request = with_bundle
    with platform as http:
        prepared = _prepare(device_state, folder, http)
    prepared.close()
    assert len(_of(record, "/sessions/branch-bundle")) == 1
    report = json.loads(_of(record, "/sessions/workspace-preparation")[0].content)
    assert report["branch"]["state"] == "checked_out", report
    assert git(folder, "rev-parse", "HEAD") == head and git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert git(folder, "rev-parse", f"refs/remotes/origin/{BRANCH}") == head
    # The device named what it has, so the platform can leave those commits out of the bundle.
    assert git(folder, "rev-parse", "main") in asked[0]

    # A local branch left at the old base is fast-forwarded from the bundle the same way.
    git(folder, "checkout", "-q", "main")
    git(folder, "branch", "-f", BRANCH, "main")
    git(folder, "update-ref", "-d", f"refs/remotes/origin/{BRANCH}")
    (server / "next.py").write_text("# the next story\n")
    git(server, "add", "-A")
    git(server, "commit", "-q", "-m", "next story")
    newer = git(server, "rev-parse", "HEAD")
    branch = workspace_prep.prepare_branch(folder, BRANCH, newer, source)
    assert branch["state"] == "checked_out" and git(folder, "rev-parse", "HEAD") == newer, branch

    # Already on the branch, and the platform pushed a newer commit since: fetched from the bundle, fast-forwarded.
    (server / "later.py").write_text("# a later commit\n")
    git(server, "add", "-A")
    git(server, "commit", "-q", "-m", "later")
    latest = git(server, "rev-parse", "HEAD")
    again = workspace_prep.prepare_branch(folder, BRANCH, latest, source)
    assert again["state"] == "already" and git(folder, "rev-parse", "HEAD") == latest, again

    # The platform cannot hand it over either: the pause names both.
    git(folder, "checkout", "-q", "main")
    git(folder, "branch", "-D", BRANCH)
    refused = workspace_prep.prepare_branch(folder, BRANCH, "f" * 40, lambda have: None)
    assert refused["state"] == "unavailable" and "nor could the platform hand it over" in refused["detail"]


# --- Teamwork: a new device folder for a repository the device cannot clone -----------------


@requires_git
def test_an_empty_folder_is_bootstrapped_from_the_platform_when_the_device_cannot_clone(device_state, tmp_path,  # noqa: F811
                                                                                         monkeypatch):
    _origin(tmp_path, monkeypatch)
    server = tmp_path / "server"
    git(tmp_path, "clone", "-q", "--branch", BRANCH, str(tmp_path / "origin.git"), str(server))
    head = git(server, "rev-parse", "HEAD")
    folder = tmp_path / "kitchen"
    folder.mkdir()
    remote = "https://bitbucket.invalid/octryx/kitchen.git"  # unreachable from here, like bitbucket.org without a key
    contract = _contract()
    contract["preparation"].update(head=head, repository={"provider": "bitbucket", "hosts": ["bitbucket.invalid"],
                                                          "path": "octryx/kitchen", "remote_url": remote})
    record: list[httpx.Request] = []
    source = _bundle_from(server, BRANCH, [])
    platform = _platform(record, ready=True, contract=contract)
    original = platform._transport.handle_request

    def with_bundle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions/branch-bundle"):
            record.append(request)
            return httpx.Response(200, json=source(json.loads(request.content)["have"]))
        return original(request)

    platform._transport.handle_request = with_bundle
    with platform as http:
        prepared = _prepare(device_state, folder, http)
    prepared.close()
    report = json.loads(_of(record, "/sessions/workspace-preparation")[0].content)
    assert report["branch"]["state"] == "checked_out", report
    assert report["remote_url"] == remote and git(folder, "remote", "get-url", "origin") == remote
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH and git(folder, "rev-parse", "HEAD") == head
    assert (folder / "NOTES.md").is_file()  # the branch's files are there
    assert json.loads(_of(record, "/sessions/branch-bundle")[0].content)["have"] == []

    # Without a repository to set it up from, nothing is created and the report says why.
    bare = tmp_path / "bare-folder"
    bare.mkdir()
    refused = workspace_prep.prepare(_contract(), bare, runtime="device")
    assert refused["branch"]["state"] == "unavailable" and "names no repository" in refused["branch"]["detail"]
    assert not (bare / ".git").exists()

    # A remote from the connection's hosts when the platform names no URL (never an API host).
    assert workspace_branch.remote_for({"hosts": ["api.bitbucket.org", "bitbucket.org"], "path": "octryx/kitchen"}) == \
        "https://bitbucket.org/octryx/kitchen.git"
