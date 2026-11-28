"""The native Windows pet, tested without Windows."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from octryx_claude.pet import account as account_module
from octryx_claude.pet import api
from octryx_claude.pet import cli as pet_cli
from octryx_claude.pet import settings as pet_settings
from octryx_claude.pet.account import TOKEN_TTL_SECONDS, WslAccount
from octryx_claude.pet.service import RUN_VALUE, PetServiceError, RunKey, instance_lock, run_command
from octryx_claude.tokens import TokenUnavailableError

BASE_URL = "https://octryx.example.test"
KIT = Path(__file__).resolve().parents[1]
TOKEN = "fake-gateway-token-for-tests-0123456789"


def _account(tmp_path, *, outputs, clock=None, config=None):
    (tmp_path / "account.json").write_text(json.dumps(config or {
        "base_url": BASE_URL, "wsl_distribution": "Ubuntu-24.04", "wsl_home": "/home/alice"}), encoding="utf-8")
    calls = []

    def runner(argv):
        calls.append(list(argv))
        result = outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(argv, result[0], stdout=result[1], stderr="")

    now = clock or [1000.0]
    return WslAccount(tmp_path, runner=runner, clock=lambda: now[0]), calls, now


def test_the_bridge_borrows_the_wsl_login_and_caches_the_token(tmp_path):
    account, calls, now = _account(tmp_path, outputs=[(0, TOKEN + "\n"), (0, TOKEN), (0, TOKEN)])
    assert account.base_url() == BASE_URL
    assert account.token(httpx.Client()) == TOKEN
    assert calls == [["wsl.exe", "-d", "Ubuntu-24.04", "-e", "/home/alice/.local/bin/octryx-claude", "api-key-helper"]]
    assert account.token(httpx.Client()) == TOKEN and len(calls) == 1  # cached
    account.token(httpx.Client(), refresh=True)
    assert len(calls) == 2
    now[0] += TOKEN_TTL_SECONDS + 1
    account.token(httpx.Client())
    assert len(calls) == 3


@pytest.mark.parametrize(("result", "code"), [
    ((1, ""), "not_logged_in"),
    ((-1, ""), "wsl_unavailable"),
    ((0, "no token here"), "wsl_unavailable"),
    (OSError("no wsl.exe"), "wsl_unavailable"),
])
def test_bridge_failures_are_fixed_codes(tmp_path, result, code):
    account, _calls, _now = _account(tmp_path, outputs=[result])
    with pytest.raises(TokenUnavailableError) as raised:
        account.token(httpx.Client())
    assert raised.value.code == code


@pytest.mark.parametrize("config", [
    {"base_url": "ftp://x", "wsl_distribution": "Ubuntu", "wsl_home": "/home/u"},
    {"base_url": BASE_URL, "wsl_distribution": "Ubuntu; calc", "wsl_home": "/home/u"},
    {"base_url": BASE_URL, "wsl_distribution": "Ubuntu", "wsl_home": "/home/u x"},
])
def test_an_unusable_account_file_is_not_used(tmp_path, config):
    account, calls, _now = _account(tmp_path, outputs=[], config=config)
    if not config["base_url"].startswith("http"):
        assert account.base_url() == ""
    else:
        with pytest.raises(TokenUnavailableError, match="not_configured"):
            account.token(httpx.Client())
    assert calls == []
    assert WslAccount(tmp_path / "missing").base_url() == ""


def test_a_401_is_retried_once_with_a_fresh_bridge_token(tmp_path):
    account, calls, _now = _account(tmp_path, outputs=[(0, "stale-token-0123456789"), (0, TOKEN)])
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer stale-token-0123456789":
            return httpx.Response(401)
        return httpx.Response(200, json={"state": "working", "items": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = api.fetch(account, http=http)
    assert result.outcome == "ok" and seen == ["Bearer stale-token-0123456789", f"Bearer {TOKEN}"] and len(calls) == 2


def test_the_run_key_starts_the_windowless_pet_at_logon_and_now(tmp_path):
    values, started = {}, []

    class FakeRegistry:
        def get(self, name):
            return values.get(name)

        def set(self, name, value):
            values[name] = value

        def delete(self, name):
            values.pop(name, None)

    python = Path(r"C:\Users\Alice Example\AppData\Local\Octryx\octryx-claude\pet\venv\Scripts\pythonw.exe")
    key = RunKey(registry=FakeRegistry(), spawn=started.append, python=python)
    key.install()
    assert values[RUN_VALUE] == subprocess.list2cmdline(run_command(python))
    assert values[RUN_VALUE].startswith(f'"{python}" -m octryx_claude.pet run')
    assert started == [run_command(python)] and key.installed()
    key.remove()
    assert not key.installed()

    class Broken(FakeRegistry):
        def set(self, name, value):
            raise PermissionError("denied")

    with pytest.raises(PetServiceError, match="registry_failed"):
        RunKey(registry=Broken(), spawn=started.append, python=python).install()


def test_one_pet_per_user(tmp_path):
    with instance_lock(tmp_path) as first:
        with instance_lock(tmp_path) as second:
            assert first and not second
    with instance_lock(tmp_path) as again:
        assert again


def test_the_pet_modules_import_without_fcntl():
    code = ("import sys; sys.modules['fcntl'] = None; "
            "import octryx_claude.pet.cli, octryx_claude.pet.account, octryx_claude.pet.api, "
            "octryx_claude.pet.runner, octryx_claude.pet.settings, octryx_claude.pet.service, "
            "octryx_claude.pet.display, octryx_claude.pet.icons, octryx_claude.pet.tray; print('ok')")
    done = subprocess.run([sys.executable, "-c", code], cwd=KIT, capture_output=True, text=True, timeout=120,
                          check=False)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr


def test_inside_wsl_the_pet_points_at_windows(tmp_path, capsys):
    assert pet_cli.in_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, tmp_path / "none")
    version = tmp_path / "version"
    version.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2", encoding="utf-8")
    assert pet_cli.in_wsl({}, version) and not pet_cli.in_wsl({}, tmp_path / "none")


def test_the_windows_entry_point_keeps_its_settings_next_to_the_account(tmp_path, monkeypatch, capsys):
    account, _calls, _now = _account(tmp_path, outputs=[(1, "")])
    monkeypatch.setattr(account_module, "default_account", lambda: account)
    monkeypatch.setattr(pet_cli, "in_wsl", lambda: False)
    assert pet_cli.main(["quiet", "22:00-07:00"]) == 0
    assert pet_settings.load(tmp_path).quiet_hours.label() == "22:00–07:00"
    monkeypatch.setattr(pet_cli, "_autostart_status", lambda _account: "no")
    assert pet_cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert f"platform:       {BASE_URL}" in out and "Signed out" in out and "(not_logged_in)" in out
