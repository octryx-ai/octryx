"""The native Windows pet updates its own venv (it lives outside WSL, where the client's self-update runs): the
platform's release, sha256 checked, pip --no-deps into the pet's venv, the new code must report the version, then the
tray ends and the new pet starts. A failed version waits an hour; OCTRYX_CLAUDE_AUTO_UPDATE=0 switches it off."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path

import httpx

from octryx_claude.pet import win_update

WHEEL = b"PK\x03\x04 fake wheel bytes"
SHA = hashlib.sha256(WHEEL).hexdigest()
NEW = "0.2.1"


class Account:
    def __init__(self, root: Path, base_url: str = "https://octryx.example.test") -> None:
        self.root = root
        self._base = base_url

    def base_url(self) -> str:
        return self._base


def _http(*, version=NEW, wheel=WHEEL, sha=SHA, release_status=200):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/octryx-claude/version"):
            return httpx.Response(release_status, json={
                "version": version, "filename": f"octryx_claude-{version}-py3-none-any.whl", "sha256": sha})
        if request.url.path == f"/octryx-claude/package/{version}":
            return httpx.Response(200, content=wheel)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


class Pip:
    def __init__(self, *, install_rc=0, reports=NEW) -> None:
        self.calls: list[list[str]] = []
        self.install_rc, self.reports = install_rc, reports

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if "pip" in argv:
            assert Path(argv[-1]).name == f"octryx_claude-{NEW}-py3-none-any.whl" and Path(argv[-1]).exists()
            return subprocess.CompletedProcess(argv, self.install_rc, "", "")
        return subprocess.CompletedProcess(argv, 0, f"{self.reports}\n", "")


def test_a_new_release_is_checked_installed_without_dependencies_and_verified(tmp_path):
    http, seen = _http()
    pip = Pip()
    got = win_update.update_once(Account(tmp_path), http=http, runner=pip, installed="0.2.0",
                                 python=Path("C:/venv/Scripts/python.exe"), env={})
    assert got == NEW
    install, check = pip.calls
    assert install[:4] == ["C:/venv/Scripts/python.exe", "-m", "pip", "install"]
    assert "--no-deps" in install and "--upgrade" in install  # Pillow/pystray stay as they are (locked .pyd files)
    assert check[1] == "-c" and "octryx_claude.pet.tray" in check[2]
    assert seen == ["/octryx-claude/version", f"/octryx-claude/package/{NEW}"]


def test_nothing_happens_on_the_same_version_off_switch_or_without_a_url(tmp_path):
    http, seen = _http(version="0.2.0")
    pip = Pip()
    assert win_update.update_once(Account(tmp_path), http=http, runner=pip, installed="0.2.0", env={}) is None
    assert pip.calls == []
    http, seen = _http()
    assert win_update.update_once(Account(tmp_path), http=http, runner=pip, installed="0.2.0",
                                  env={"OCTRYX_CLAUDE_AUTO_UPDATE": "0"}) is None
    assert seen == [] and pip.calls == []
    assert win_update.update_once(Account(tmp_path, base_url=""), http=http, runner=pip, installed="0.2.0",
                                  env={}) is None


def test_a_wrong_digest_or_failed_install_or_check_keeps_the_pet_and_waits_an_hour(tmp_path):
    for http_args, pip in (({"sha": "0" * 64}, Pip()), ({}, Pip(install_rc=1)), ({}, Pip(reports="0.2.0"))):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        http, _ = _http(**http_args)
        assert win_update.update_once(Account(root), http=http, runner=pip, installed="0.2.0", now=1000.0,
                                      env={}) is None
        again = Pip()
        http, seen = _http()
        assert win_update.update_once(Account(root), http=http, runner=again, installed="0.2.0", now=1000.0 + 600,
                                      env={}) is None  # the same version is not tried again within the hour
        assert again.calls == [] and seen == ["/octryx-claude/version"]
    digest_case = Pip()
    http, _ = _http(sha="0" * 64)
    win_update.update_once(Account(tmp_path / "d"), http=http, runner=digest_case, installed="0.2.0", env={})
    assert digest_case.calls == []  # a wrong package is never installed


def test_an_unreachable_platform_changes_nothing(tmp_path):
    http, _ = _http(release_status=503)
    pip = Pip()
    assert win_update.update_once(Account(tmp_path), http=http, runner=pip, installed="0.2.0", env={}) is None
    assert pip.calls == []


def test_the_watcher_hands_over_once_and_ends(tmp_path):
    results = iter([None, NEW])
    handed: list[str] = []
    stop = threading.Event()
    win_update.watch(Account(tmp_path), stop, handed.append, check=lambda: next(results), interval=0.01)
    assert handed == [NEW]
    failing = iter([RuntimeError("boom")])

    def explode():
        raise next(failing)

    stop.set()
    win_update.watch(Account(tmp_path), stop, handed.append, check=explode, interval=0.01)  # stopped: no round
    assert handed == [NEW]


def test_pet_run_ends_the_tray_on_an_update_and_only_on_windows(tmp_path, monkeypatch):
    from octryx_claude.pet import cli

    class Tray:
        quits = 0

        def quit(self):
            Tray.quits += 1

    updated: list[str] = []
    assert cli._start_windows_updates(Account(tmp_path), Tray(), updated)() is None  # not Windows: nothing starts
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(win_update, "watch", lambda account, stop, handover: handover(NEW))
    stop = cli._start_windows_updates(Account(tmp_path), Tray(), updated)
    for _ in range(100):
        if updated:
            break
        threading.Event().wait(0.01)
    monkeypatch.setattr(cli.os, "name", "posix")
    stop()
    assert updated == [NEW] and Tray.quits == 1


def test_updates_only_over_https_or_a_local_test_platform(tmp_path):
    # The digest comes from the same server; over http an attacker could hand over both
    for url in ("http://octryx.example.test", "http://localhost.evil.test", "ftp://octryx.example.test",
                "http://127.0.0.1.evil.test"):
        http, seen = _http()
        pip = Pip()
        assert win_update.update_once(Account(tmp_path, base_url=url), http=http, runner=pip, installed="0.2.0",
                                      env={}) is None, url
        assert seen == [] and pip.calls == [], url
    for url in ("https://octryx.example.test", "http://localhost:8000", "http://127.0.0.1:8090", "http://localhost"):
        assert win_update.trusted_base_url(url), url
