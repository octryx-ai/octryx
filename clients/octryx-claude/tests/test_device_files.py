"""Files a phone turn made on the Mac: listed by name after the turn, sent only on request and only from its folder."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from octryx_claude import device_files
from octryx_claude.device_files import FileServer, changed_files, remember_turn, resolve, shared_folder
from octryx_claude.device_sdk_events import secret_path
from octryx_claude.state import LocalState


@pytest.fixture
def work():
    """A project folder (temp folders are never shared): inside the checkout, removed after."""
    folder = Path(__file__).resolve().parent / "_work" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder.parent, ignore_errors=True)


def _touch(path, content: bytes = b"x", mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_lists_only_new_shareable_files(work):
    old = time.time() - 3600
    _touch(work / "report.md", b"# Report")
    _touch(work / "docs" / "chart.png", b"png")
    _touch(work / "old.txt", b"old", mtime=old)
    _touch(work / ".env", b"SECRET=1")
    _touch(work / ".zsh_history", b"export TOKEN=x")
    _touch(work / ".kube" / "config", b"cluster")
    _touch(work / "Library" / "Cookies" / "Cookies.binarycookies", b"c")
    _touch(work / "keys" / "server.pem", b"key")
    _touch(work / ".git" / "HEAD", b"ref")
    _touch(work / "node_modules" / "x" / "index.js", b"js")
    (work / "link.md").symlink_to(work / "report.md")
    found = changed_files(str(work), time.time() - 60)
    assert sorted(item["path"] for item in found) == ["docs/chart.png", "report.md"]
    assert set(found[0]) == {"path", "size", "mtime"}


def test_resolves_only_inside_a_remembered_job_folder(tmp_path, work):
    state = LocalState(tmp_path / "state")
    _touch(work / "out" / "a.txt", b"hello")
    _touch(work / ".env", b"SECRET=1")
    _touch(work / ".config" / "gh" / "hosts.yml", b"token")
    _touch(work / "Library" / "x.txt", b"x")
    _touch(tmp_path / "outside.txt", b"nope")
    (work / "escape.txt").symlink_to(tmp_path / "outside.txt")
    assert resolve(state, "job1", "out/a.txt") == (None, "unknown_job")
    remember_turn(state, "job1", str(work), time.time())
    assert resolve(state, "job1", "out/a.txt")[0] == (work / "out" / "a.txt").resolve()
    assert resolve(state, "job1", "../outside.txt") == (None, "invalid_path")
    assert resolve(state, "job1", "/etc/passwd") == (None, "invalid_path")
    assert resolve(state, "job1", "escape.txt") == (None, "outside_folder")
    assert resolve(state, "job1", ".env") == (None, "not_shared")
    assert resolve(state, "job1", ".config/gh/hosts.yml") == (None, "not_shared")
    assert resolve(state, "job1", "Library/x.txt") == (None, "not_shared")
    assert resolve(state, "job1", "missing.txt") == (None, "not_found")
    assert resolve(state, "job2", "out/a.txt") == (None, "unknown_job")


def test_serves_a_file_in_chunks_or_says_why_not(tmp_path, work, monkeypatch):
    monkeypatch.setattr(device_files, "CHUNK_BYTES", 4)
    state = LocalState(tmp_path / "state")
    content = b"0123456789"
    _touch(work / "a.bin", content)
    remember_turn(state, "job1", str(work), time.time())
    sent: list[tuple[str, dict[str, Any]]] = []

    async def send(message_type: str, body: dict[str, Any]) -> bool:
        sent.append((message_type, body))
        return True

    server = FileServer(state, send)
    asyncio.run(server.serve({"request_id": "r1", "job_id": "job1", "path": "a.bin"}))
    chunks = [body for kind, body in sent if kind == "file_chunk"]
    assert [chunk["seq"] for chunk in chunks] == [0, 1, 2]
    assert b"".join(base64.b64decode(chunk["data"]) for chunk in chunks) == content
    assert chunks[-1]["last"] is True and chunks[-1]["sha256"] == hashlib.sha256(content).hexdigest()
    sent.clear()
    asyncio.run(server.serve({"request_id": "r2", "job_id": "job1", "path": "../x"}))
    assert sent == [("file_failed", {"request_id": "r2", "reason": "invalid_path"})]
    sent.clear()
    asyncio.run(server.serve({"request_id": "bad id!", "job_id": "job1", "path": "a.bin"}))
    assert sent == []


def test_home_disks_temp_system_and_config_folders_share_nothing(tmp_path, work):
    """A take-over session started in ``~`` must not list or serve credentials or app data."""
    home = work / "Users" / "alice"
    _touch(home / ".zsh_history", b"export TOKEN=x")
    _touch(home / "Library" / "Keychains" / "login.keychain-db", b"k")
    _touch(home / "notes.md", b"n")
    state = LocalState(home / ".octryx" / "claude")
    assert shared_folder(str(home), home=home) is None
    assert changed_files(str(home), 0, home=home) == []
    remember_turn(state, "job1", str(home), time.time())
    assert resolve(state, "job1", "notes.md", home=home) == (None, "folder_not_shared")
    for folder in ("/", "/Users", "/Volumes/SSD", "/tmp/x", "/private/var/folders/x", "/etc/x", "/opt/homebrew",
                   str(home / "Library" / "x"), str(home / ".config" / "x"), str(home / ".claude" / "projects"),
                   str(home / ".octryx"), str(state.root)):
        assert shared_folder(folder, home=home, state_root=state.root) is None, folder
    (home / ".claude-private").mkdir()
    assert shared_folder(str(home / ".claude-private" / "x"), home=home) is None
    project = home / "projects" / "app"
    project.mkdir(parents=True)
    assert shared_folder(str(project), home=home, state_root=state.root) == project.resolve()


def test_secret_path_knows_stores_histories_and_cli_logins():
    for path in ("/Users/l/Library/Keychains/login.keychain-db",
                 "/Users/l/Library/Application Support/Google/Chrome/Default/Cookies",
                 "/Users/l/Library/Application Support/Google/Chrome/Default/Login Data",
                 "/Users/l/.zsh_history", "/Users/l/.bash_history", "/Users/l/.kube/config",
                 "/Users/l/.docker/config.json", "/Users/l/.config/gh/hosts.yml",
                 "/Users/l/.octryx/device.json", "/Users/l/.claude/.credentials.json", "/x/.netrc"):
        assert secret_path(path), path
    assert not secret_path("/Users/l/projects/app/report.md")
