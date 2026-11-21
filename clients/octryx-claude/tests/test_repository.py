"""Repository detection, credential-free remotes, ls-tree parsing and blob reads."""

from __future__ import annotations

import hashlib

from octryx_claude import repository
from octryx_claude.repository import DetectionRefusal, RepositoryInfo, credential_free_remote

from .gitrepo import STRIPPED_REMOTE, git, make_repo, requires_git


def test_remote_credentials_are_stripped_and_scp_form_is_kept():
    assert credential_free_remote("https://user:tok@github.com/o/r.git") == STRIPPED_REMOTE
    assert credential_free_remote("https://ghp_abc@github.com/o/r.git?x=1#f") == STRIPPED_REMOTE
    assert credential_free_remote("http://u:p@git.local:8080/o/r") == "http://git.local:8080/o/r"
    assert credential_free_remote("git@github.com:o/r.git") == "git@github.com:o/r.git"
    assert credential_free_remote("ssh://git:secret@host/o/r.git") == "ssh://git@host/o/r.git"


def test_ls_tree_parsing_keeps_regular_blobs_and_bounds_the_listing():
    sha = "a" * 40
    output = (
        f"100644 blob {sha} 12\tsrc/a.py\0".encode()
        + f"100755 blob {sha} 3\tbin/run\0".encode()
        + f"120000 blob {sha} 9\tlink\0".encode()
        + f"160000 commit {sha} -\tvendor/sub\0".encode()
        + f"100644 blob {sha} 5\twith space\tand tab.txt\0".encode()
    )
    listing = repository.parse_ls_tree(output)
    assert [(f.path, f.size) for f in listing.files] == [("src/a.py", 12), ("bin/run", 3),
                                                         ("with space\tand tab.txt", 5)]
    assert listing.truncated is False
    bounded = repository.parse_ls_tree(output, limit=2)
    assert len(bounded.files) == 2 and bounded.truncated is True


@requires_git
def test_detects_the_repository_and_reads_head(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)

    info = repository.detect_repository(repo / "src")
    assert isinstance(info, RepositoryInfo)
    assert info.root.resolve() == repo.resolve()
    assert info.remote_url == STRIPPED_REMOTE
    assert info.head_commit == git(repo, "rev-parse", "HEAD") and len(info.head_commit) == 40
    assert info.head_dirty is False and info.head_pushed is False and info.branch == "main"

    (repo / "README.md").write_text("# changed\n")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    again = repository.detect_repository(repo)
    assert again.head_dirty is True and again.head_pushed is True

    listing = repository.list_head_files(repo)
    by_path = {item.path: item for item in listing.files}
    assert set(by_path) == {"README.md", "src/app.py"}  # the symlink is skipped
    assert by_path["src/app.py"].size == len("print('hello')\n")

    blobs = repository.read_blobs(repo, [by_path["README.md"].blob_sha, by_path["src/app.py"].blob_sha, "f" * 40])
    assert blobs == {by_path["README.md"].blob_sha: b"# demo\n", by_path["src/app.py"].blob_sha: b"print('hello')\n"}
    content = b"# demo\n"
    assert hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest() == by_path["README.md"].blob_sha


@requires_git
def test_refusals_are_explicit_codes(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)  # isolates the git config
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert repository.detect_repository(plain) == DetectionRefusal("not_a_git_repository")

    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    assert repository.detect_repository(empty) == DetectionRefusal("head_missing")

    monkeypatch.setenv("PATH", str(tmp_path / "no-bin"))
    assert repository.detect_repository(plain) == DetectionRefusal("git_unavailable")
