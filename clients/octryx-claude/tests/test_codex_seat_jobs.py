from __future__ import annotations

import asyncio
import contextlib
import json
import stat
import sys
import threading
import tomllib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from octryx_claude import codex_driver, codex_seat
from tests.codex_appserver_fake import fake_appserver
from tests.codex_driver_support import _stop_replay

SEAT_RESPONSES = "/api/v1/model-gateway/openai/seat/responses"


def _prepared(tmp_path: Path, base_url: str = "https://platform.test") -> SimpleNamespace:
    session = tmp_path / "sessions" / "k1"
    session.mkdir(parents=True)
    state = tmp_path / "state"
    (codex_seat.ensure_seat_home(state) / "auth.json").write_text("{}")
    return SimpleNamespace(
        session_key="k1", model="", profile="seat", settings_path=session / "settings.json",
        env={"PATH": "/usr/bin:/bin", "OCTRYX_SESSION_KEY": "k1", "OCTRYX_CLAUDE_HOME": str(state)},
        extra={"gateway": {"base_url": base_url, "session_key": "k1", "workspace_id": "w1", "workflow_run": ""},
               "hook_shim": "/opt/octryx/bin/octryx-claude", "permission_mode": "bypassPermissions",
               "codex_seat": True, "seat_credential": "seat-cred-123", "state_root": str(state)})


@contextlib.contextmanager
def _platform() -> Iterator[tuple[str, list[tuple[str, dict[str, str]]]]]:
    seen: list[tuple[str, dict[str, str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append((self.path, {name.lower(): value for name, value in self.headers.items()}))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


def _seat_calls(seen: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    return [headers for path, headers in seen if path == SEAT_RESPONSES]


def _review_codex_that_calls_its_provider(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "codex"
    script.write_text(
        f"#!{sys.executable}\nimport json, os, sys, tomllib, urllib.request\n"
        "home = os.environ['CODEX_HOME']\n"
        "provider = tomllib.load(open(os.path.join(home, 'config.toml'), 'rb'))['model_providers']['octryx_seat']\n"
        "headers = {name: os.environ[env] for name, env in provider['env_http_headers'].items()}\n"
        "headers.update(provider['http_headers'], authorization='Bearer chatgpt')\n"
        "headers['content-type'] = 'application/json'\n"
        "request = urllib.request.Request(provider['base_url'] + '/responses',\n"
        "                                 data=json.dumps({'model': 'm'}).encode(), headers=headers, method='POST')\n"
        "urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10)\n"
        "open(sys.argv[sys.argv.index('-o') + 1], 'w').write('{\"verdict\": \"pass\"}')\n"
        "print(json.dumps({'type': 'thread.started', 'thread_id': 't1'}), flush=True)\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {}}), flush=True)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_codex_on_the_seat_points_at_the_platforms_seat_route_with_only_the_seat_credential(tmp_path):
    prepared = _prepared(tmp_path)
    home = codex_driver.prepare_home(prepared, sandboxed=False)
    config = (home / "config.toml").read_text()
    provider = tomllib.loads(config)["model_providers"]["octryx_seat"]
    assert provider["base_url"] == "https://platform.test/api/v1/model-gateway/openai/seat"
    assert provider["env_http_headers"] == {"X-Octryx-Seat-Credential": codex_seat.SEAT_CREDENTIAL_ENV}
    assert "supports_standalone_web_search" not in provider
    assert codex_driver.environment(prepared, home)[codex_seat.SEAT_CREDENTIAL_ENV] == "seat-cred-123"
    assert "seat-cred-123" not in config


def test_a_seat_job_sends_codexs_calls_to_the_platforms_seat_route(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    monkeypatch.setattr(plain_driver, "judged_stop", _stop_replay((None, True)))
    codex = fake_appserver(tmp_path / "bin", turns=[[
        {"call_provider": True},
        {"notify": "item/completed", "params": {"item": {"id": "m", "type": "agentMessage", "text": "Done."}}}]])

    async def emit(_event):
        return None

    with _platform() as (base_url, seen):
        result = asyncio.run(codex_driver.CodexDriver(str(codex)).run_turn(
            _prepared(tmp_path, base_url), cwd=str(tmp_path), prompt="Build S1", resume=None, emit=emit))

    assert result["status"] == "success"
    assert json.loads((tmp_path / "bin" / "seen.json").read_text())["status"] == 200
    [call] = _seat_calls(seen)
    assert (call["x-octryx-seat-credential"], call["authorization"]) == ("seat-cred-123", "Bearer chatgpt")


def test_a_codex_seat_review_sends_its_call_to_the_platforms_seat_route_too(tmp_path):
    from octryx_claude.review_call import ReviewCallDriver

    posted: list[dict] = []

    def control(method, path, body):
        if method == "GET":
            return True, {"turn_id": "t1", "system": "Review.", "user": "The change.", "model": "gpt-6-luna"}
        posted.append(body)
        return True, {"state": "recorded"}

    with _platform() as (base_url, seen):
        prepared = _prepared(tmp_path, base_url)
        prepared.cli_path = str(_review_codex_that_calls_its_provider(tmp_path / "bin"))
        result = asyncio.run(ReviewCallDriver(control, engine="codex").run_turn(
            prepared, cwd=str(tmp_path), prompt="p", resume=None))

    assert result["status"] == "success" and posted[0]["text"] == '{"verdict": "pass"}'
    [call] = _seat_calls(seen)
    assert call["x-octryx-seat-credential"] == "seat-cred-123"


def test_engine_made_folders_never_enter_the_change(tmp_path):
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
