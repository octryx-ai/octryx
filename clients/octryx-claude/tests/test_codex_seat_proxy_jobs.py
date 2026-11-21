"""The platform decides the seat traffic's way, and a device seat job or review runs Codex through its own proxy."""

from __future__ import annotations

import asyncio
import json
import stat
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from octryx_claude import codex_config, codex_driver, codex_seat
from octryx_claude.codex_seat_proxy import PROXY_TOKEN_ENV, SeatProxy
from octryx_claude.seat_proxy_http import PROXY_TOKEN_HEADER
from tests.codex_seat_proxy_support import Fakes

# --- Codex's configuration and the job ----------------------------------------------------------------------------


def _prepared(tmp_path: Path, traffic: str) -> SimpleNamespace:
    session = tmp_path / "sessions" / "k1"
    session.mkdir(parents=True)
    state = tmp_path / "state"
    (codex_seat.ensure_seat_home(state) / "auth.json").write_text("{}")
    return SimpleNamespace(
        session_key="k1", model="", profile="seat", settings_path=session / "settings.json",
        env={"PATH": "/usr/bin:/bin", "OCTRYX_SESSION_KEY": "k1", "OCTRYX_CLAUDE_HOME": str(state)},
        extra={"gateway": {"base_url": "https://platform.test", "session_key": "k1", "workspace_id": "w1",
                           "workflow_run": ""}, "hook_shim": "/opt/octryx/bin/octryx-claude",
               "permission_mode": "bypassPermissions", "codex_seat": True, "seat_credential": "seat-cred-123",
               "state_root": str(state),
               codex_seat.EXTRA_TRAFFIC: codex_seat.seat_traffic({"codex_seat": {"seat_traffic": traffic}})})


def _codex_that_calls_its_provider(folder: Path) -> Path:
    """A ``codex`` that reads its provider from config.toml and posts one call there, as Codex would."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "codex"
    script.write_text(
        f"#!{sys.executable}\nimport json, os, tomllib, urllib.request\n"
        "home = os.environ['CODEX_HOME']\n"
        "provider = tomllib.load(open(os.path.join(home, 'config.toml'), 'rb'))['model_providers']['octryx_seat']\n"
        "headers = {name: os.environ[env] for name, env in provider['env_http_headers'].items()}\n"
        "headers.update(provider['http_headers'], authorization='Bearer chatgpt')\n"
        "headers['content-type'] = 'application/json'\n"
        "request = urllib.request.Request(provider['base_url'] + '/responses',\n"
        "                                 data=json.dumps({'model': 'm'}).encode(), headers=headers, method='POST')\n"
        "opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
        "status = opener.open(request, timeout=10).status\n"
        f"json.dump({{'status': status, 'url': provider['base_url']}}, open({str(folder / 'seen.json')!r}, 'w'))\n"
        "import sys\n"
        "if '-o' in sys.argv:\n"
        "    open(sys.argv[sys.argv.index('-o') + 1], 'w').write('{\"verdict\": \"pass\"}')\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 't1'}), flush=True)\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {}}), flush=True)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.parametrize(("policy", "traffic"), [
    ({"codex_seat": {"seat_traffic": "device"}}, "device"), ({"codex_seat": {"seat_traffic": "gateway"}}, "gateway"),
    ({"codex_seat": {"allowed": True}}, "gateway"), ({}, "gateway")])  # a platform without the switch relays itself
def test_the_platform_decides_the_way(policy, traffic):
    assert codex_seat.seat_traffic(policy) == traffic


def test_codex_points_at_the_proxy_on_device_and_at_the_seat_route_on_gateway(tmp_path):
    device = _prepared(tmp_path / "d", "device")
    home = codex_driver.prepare_home(device, sandboxed=False, seat_proxy="http://127.0.0.1:48123")
    provider = tomllib.loads((home / "config.toml").read_text())["model_providers"]["octryx_seat"]
    assert provider["base_url"] == "http://127.0.0.1:48123"
    assert provider["env_http_headers"] == {"X-Octryx-Seat-Credential": codex_seat.SEAT_CREDENTIAL_ENV,
                                            PROXY_TOKEN_HEADER: PROXY_TOKEN_ENV}
    assert codex_driver.environment(device, home, proxy_token="job-token")[PROXY_TOKEN_ENV] == "job-token"
    assert "job-token" not in (home / "config.toml").read_text() + (home / codex_config.ENV_WRAPPER).read_text()

    gateway = _prepared(tmp_path / "g", "gateway")
    home = codex_driver.prepare_home(gateway, sandboxed=False)
    provider = tomllib.loads((home / "config.toml").read_text())["model_providers"]["octryx_seat"]
    assert provider["base_url"] == "https://platform.test/api/v1/model-gateway/openai/seat"
    assert PROXY_TOKEN_HEADER not in provider["env_http_headers"]
    assert PROXY_TOKEN_ENV not in codex_driver.environment(gateway, home)


def test_a_device_seat_job_runs_codex_through_its_own_proxy_which_stops_with_the_job(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    monkeypatch.setattr(plain_driver, "replay_stop", lambda prepared, cwd: None)
    fakes = Fakes()
    started: list[SeatProxy] = []

    def factory(base_url: str) -> SeatProxy:
        started.append(fakes.proxy(base_url))
        return started[-1]

    codex = _codex_that_calls_its_provider(tmp_path / "bin")
    prepared = _prepared(tmp_path, "device")

    async def emit(_event):
        return None

    result = asyncio.run(codex_driver.CodexDriver(str(codex), proxy_factory=factory).run_turn(
        prepared, cwd=str(tmp_path), prompt="Build S1", resume=None, emit=emit))

    seen = json.loads((tmp_path / "bin" / "seen.json").read_text())
    [proxy] = started
    assert result["status"] == "success" and seen == {"status": 200, "url": f"http://127.0.0.1:{proxy.port}"}
    assert [kind for kind, _ in fakes.calls] == ["admit", "upstream", "report"]
    assert proxy._server is None  # stopped with the job

    gateway = _prepared(tmp_path / "gw", "gateway")  # the platform relays: no proxy is started
    assert asyncio.run(codex_driver.CodexDriver(str(codex), proxy_factory=factory)._start_proxy(gateway)) is None
    assert len(started) == 1


def test_a_codex_seat_review_runs_through_its_own_proxy_too(tmp_path):
    """A Codex seat review call goes through the turn's own loopback proxy, never the relay route (which refuses it
    ``codex_seat_traffic_device``)."""
    from octryx_claude.review_call import ReviewCallDriver

    fakes = Fakes()
    started: list[SeatProxy] = []

    def factory(base_url: str) -> SeatProxy:
        started.append(fakes.proxy(base_url))
        return started[-1]

    prepared = _prepared(tmp_path, "device")
    prepared.cli_path = str(_codex_that_calls_its_provider(tmp_path / "bin"))
    posted: list[dict] = []

    def control(method, path, body):
        if method == "GET":
            return True, {"turn_id": "t1", "system": "Review.", "user": "The change.", "model": "gpt-6-luna"}
        posted.append(body)
        return True, {"state": "recorded"}

    result = asyncio.run(ReviewCallDriver(control, engine="codex", proxy_factory=factory).run_turn(
        prepared, cwd=str(tmp_path), prompt="p", resume=None))

    seen = json.loads((tmp_path / "bin" / "seen.json").read_text())
    [proxy] = started
    assert result["status"] == "success" and seen == {"status": 200, "url": f"http://127.0.0.1:{proxy.port}"}
    assert [kind for kind, _ in fakes.calls] == ["admit", "upstream", "report"]
    assert posted[0]["text"] == '{"verdict": "pass"}' and proxy._server is None  # answered, proxy stopped


def test_engine_made_folders_never_enter_the_change(tmp_path):
    """Story path audit: an engine that installs before it writes the app's .gitignore must not put
    node_modules or a Playwright browser into the change; the repository's exclude list keeps them out at any depth."""
    import subprocess

    from octryx_claude import run_contract, work_git

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                              cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "README.md").write_text("x\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    app = tmp_path / "coffee" / "web" / "codex"
    for folder in ("node_modules/pkg", ".playwright-browsers/chromium-1", "test-results", ".npm-cache"):
        (app / folder).mkdir(parents=True)
        (app / folder / "blob.bin").write_bytes(b"\0" * 1000)
    (app / "app.js").write_text("console.log(1);\n")
    work_git.exclude_runtime_files(tmp_path)
    change = run_contract.change(tmp_path, base)
    assert "coffee/web/codex/app.js" in change["patch"]
    assert not any(name in change["patch"] for name in ("node_modules", ".playwright-browsers", "test-results",
                                                        ".npm-cache"))
