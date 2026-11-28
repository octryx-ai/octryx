from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from octryx_claude import os_junk
from octryx_claude.contract_change import change
from octryx_claude.pipeline_green import tree_digest
from tests.gitrepo import git, make_repo, requires_git

JUNK = (".DS_Store", "src/.DS_Store", "src/._app.py", "docs/Thumbs.db", "desktop.ini", ".Spotlight-V100/Store-V2/x",
        "src/.fseventsd/fseventsd-uuid")


def _junk(repo: Path) -> None:
    for name in JUNK:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00\x01Bud1 finder state")


def _server_tree(repo: Path, base: str, patch: str, scratch: Path) -> str:
    env = {**os.environ, "GIT_INDEX_FILE": str(scratch / "index")}
    subprocess.run(["git", "read-tree", base], cwd=repo, env=env, check=True)
    subprocess.run(["git", "apply", "--cached", "--binary", "-"], cwd=repo, env=env, input=patch.encode(), check=True)
    return subprocess.run(["git", "write-tree"], cwd=repo, env=env, capture_output=True, text=True,
                          check=True).stdout.strip()


@requires_git
def test_os_files_stay_out_of_the_change_and_the_device_tree_matches_the_servers(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    base = git(repo, "rev-parse", "HEAD")
    (repo / "src" / "app.py").write_text("print('fixed')\n")
    (repo / "src" / "new.py").write_text("x = 1\n")
    _junk(repo)

    result = change(repo, base)

    assert result.get("patch") and not result.get("base_unavailable"), result
    assert "src/new.py" in result["patch"]
    assert not [name for name in JUNK if name in result["patch"]]
    assert tree_digest(repo) == _server_tree(repo, base, result["patch"], tmp_path)


@requires_git
def test_the_device_tree_sees_a_same_size_edit_made_in_the_second_of_the_last_commit(tmp_path, monkeypatch):
    # The digest's index copy keeps the index's mtime, so git re-reads racily clean entries.
    while time.time() % 1 > 0.3:  # commit and edit early in one second
        time.sleep(0.01)
    repo = make_repo(tmp_path, monkeypatch)
    (repo / "src" / "app.py").write_text("print('fixed')\n")  # the same size as the committed line
    time.sleep(1.1)  # the digest runs in a later second than the commit and the edit
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "fresh-index")}
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    truth = subprocess.run(["git", "write-tree"], cwd=repo, env=env, capture_output=True, text=True,
                           check=True).stdout.strip()

    assert tree_digest(repo) == truth


@requires_git
def test_a_tracked_os_file_keeps_its_committed_version(tmp_path, monkeypatch):
    # A repository that committed one (some do) is not changed by the exclusion: no deletion appears.
    repo = make_repo(tmp_path, monkeypatch)
    (repo / ".DS_Store").write_bytes(b"committed")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "tracked")
    base = git(repo, "rev-parse", "HEAD")
    (repo / ".DS_Store").write_bytes(b"rewritten by Finder")
    (repo / "README.md").write_text("# changed\n")

    patch = change(repo, base)["patch"]

    assert "README.md" in patch and ".DS_Store" not in patch


def test_the_list_is_data():
    assert os_junk.DATA.name == "os_junk.json" and os_junk.DATA.is_file()
    assert ":(exclude,glob)**/.DS_Store" in os_junk.excludes()
    assert ":(exclude,glob)**/.Spotlight-V100/**" in os_junk.excludes()
