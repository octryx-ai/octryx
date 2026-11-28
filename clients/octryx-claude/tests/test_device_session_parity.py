"""A device job turn is set up like a terminal session."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from octryx_claude import launch, launch_settings, run_contract
from octryx_claude.device_session import SessionRefusedError, prepare_session
from octryx_claude.platform import ENV_WORKFLOW_RUN, HEADER_WORKFLOW_RUN, SessionContext
from octryx_claude.tokens import GATEWAY_AUDIENCE
from tests.gitrepo import make_repo, requires_git

RUN = "0b6a1c1e-4f7d-4c84-9a52-1f2d3c4b5a69"
BASE = "https://octryx.example.test"
CONTRACT = {"digest": "d1", "run": {"id": RUN, "branch": "feature/orders-total"},
            "phase": {"node_id": "tests_first", "protected_files": []}}


@pytest.fixture
def device_state(short_state, monkeypatch):
    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    short_state.with_credential_set("device").write_credentials({
        "base_url": BASE, "client_id": "oec_test", "refresh_token": "device-refresh",
        "tokens": {GATEWAY_AUDIENCE: {"access_token": "device-gateway", "expires_at": time.time() + 3600}}})
    return short_state


def _answer(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body, headers={"x-octryx-gateway-state": str(body.get("state") or ""),
                                                      "x-octryx-gateway-reason": str(body.get("reason") or "")})


def _platform(record: list, *, register: tuple[int, dict] | None = None, bind: tuple[int, dict] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        path = request.url.path
        if path.endswith("/client-policy"):
            return httpx.Response(200, json={"state": "allowed"})
        if path.endswith("/sessions/register"):
            status, body = register or (200, {"state": "registered", "workflow_run_attach": {"state": "attached"},
                                              "workflow_run": CONTRACT})
            return _answer(status, body)
        if path.endswith("/sessions/hook-key"):
            return httpx.Response(200, json={"state": "registered"})
        if path.endswith("/sessions/repository"):
            status, body = bind or (200, {"state": "bound", "binding": {"repository": "o/r", "workspace_id": "ws-1"},
                                          "snapshot": {"state": "denied", "reason": "local_snapshots_not_allowed"}})
            return _answer(status, body)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _prepare(state, folder: Path | str, http, *, run: str = RUN):
    return prepare_session(state, base_url=BASE, workspace_id="ws-1", profile="governed", folder=str(folder),
                           http=http, shim=Path("/bin/octryx-claude"), workflow_run=run)


def _of(record: list, suffix: str) -> list[httpx.Request]:
    return [request for request in record if request.url.path.endswith(suffix)]


@requires_git
def test_a_run_bound_turn_registers_with_its_run_and_binds_the_folders_repository(device_state, tmp_path,
                                                                                  monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    record: list[httpx.Request] = []
    with _platform(record) as http:
        prepared = _prepare(device_state, repo, http)
    try:
        # Every control-plane call carries the job's run: registration binds the session to it on the platform.
        assert {request.headers.get(HEADER_WORKFLOW_RUN) for request in record} == {RUN}
        # The run contract is remembered for the hooks exactly as at a terminal launch.
        assert run_contract.current(device_state, prepared.session_key) == CONTRACT
        # The terminal's code intelligence bound the folder: credential-free remote, HEAD and the root.
        bound = json.loads(_of(record, "/sessions/repository")[0].content)
        assert bound["remote_url"] == "https://github.com/o/r.git"
        assert bound["root"] == str(repo.resolve()) and len(bound["head_commit"]) == 40
        # The hooks inherit the run and send it too.
        assert prepared.env[ENV_WORKFLOW_RUN] == RUN
        assert SessionContext.from_env(prepared.env).headers()[HEADER_WORKFLOW_RUN] == RUN
    finally:
        prepared.close()


@requires_git
def test_the_platforms_refusals_end_the_turn_with_their_reason(device_state, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    mismatch = (403, {"state": "denied", "reason": "repository_not_run_repository"})
    with _platform([], bind=mismatch) as http, pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, repo, http)
    assert refused.value.code == "repository_not_run_repository"

    outside = (403, {"state": "denied", "reason": "folder_not_allowed_on_device"})
    with _platform([], bind=outside) as http, pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, repo, http, run="")  # any turn, with or without a run
    assert refused.value.code == "folder_not_allowed_on_device"

    not_followed = (403, {"state": "denied", "reason": "run_read_only"})
    with _platform([], register=not_followed) as http, pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, repo, http)
    assert refused.value.code == "registration_denied_run_read_only"

    unattached = (200, {"state": "registered"})
    with _platform([], register=unattached) as http, pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, repo, http)
    assert refused.value.code == "workflow_run_not_attached"


def test_a_run_bound_turn_needs_a_git_repository_a_free_turn_does_not(device_state, tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    record: list[httpx.Request] = []
    with _platform(record) as http, pytest.raises(SessionRefusedError) as refused:
        _prepare(device_state, folder, http)
    assert refused.value.code == "repository_not_a_git_repository"
    branchless = {**CONTRACT, "run": {"id": RUN, "branch": None}}  # a run that works in no repository
    attached = (200, {"state": "registered", "workflow_run_attach": {"state": "attached"}, "workflow_run": branchless})
    with _platform(record, register=attached) as http:
        _prepare(device_state, folder, http).close()
    with _platform(record, register=(200, {"state": "registered"})) as http:
        prepared = _prepare(device_state, folder, http, run="")
    prepared.close()  # code intelligence is off, as in a terminal outside a repository


def test_a_codex_seat_turn_ignores_a_phases_fixed_claude_model(device_state, tmp_path, monkeypatch):
    # ChatGPT has no claude-* model, so the Codex seat turn runs on Codex's own default.
    from octryx_claude import codex_driver, codex_seat

    monkeypatch.setattr(codex_driver, "resolve_codex", lambda: "/usr/local/bin/codex")
    monkeypatch.setattr(codex_seat, "logged_in", lambda codex, root: True)
    seat = (200, {"state": "registered", "seat_credential": "c" * 43})
    with _platform([], register=seat) as http:
        prepared = prepare_session(device_state, base_url=BASE, workspace_id="ws-1", profile="seat",
                                   folder=str(tmp_path), http=http, shim=Path("/bin/octryx-claude"),
                                   model="claude-haiku-5-5", engine="codex")
    try:
        assert prepared.model == "" and prepared.extra.get("codex_seat") is True
    finally:
        prepared.close()

    # The device's own Codex seat model (``codex_seat_model``) takes the dropped model's place.
    device_state.write_config({**device_state.config(), "codex_seat_model": "gpt-6-luna"})
    with _platform([], register=seat) as http:
        chosen = prepare_session(device_state, base_url=BASE, workspace_id="ws-1", profile="seat",
                                 folder=str(tmp_path), http=http, shim=Path("/bin/octryx-claude"),
                                 model="claude-haiku-5-5", engine="codex")
    try:
        assert chosen.model == "gpt-6-luna"
    finally:
        chosen.close()


# The file Claude Code 2.1.318 wrote for a platform server that answered 401 (reproduced with
# ``--strict-mcp-config --mcp-config``, as the launcher starts it); only the keys and the value's shape are kept.
NEEDS_AUTH_CACHE = {launch_settings.MCP_SERVER_NAME: {"timestamp": 1795164655664},
                    "plugin:cloudflare:cloudflare-api": {"timestamp": 1795164655664}}


@requires_git
def test_a_needs_auth_mark_for_the_platform_server_is_removed_and_the_session_keeps_its_tools(device_state, tmp_path,
                                                                                              monkeypatch):
    # A mark one broken turn left must not cost the following turns submit_reproduction and the other platform tools.
    repo = make_repo(tmp_path, monkeypatch)
    config_dir = device_state.claude_config_dir_for("governed")
    config_dir.mkdir(parents=True, exist_ok=True)
    cache = config_dir / "mcp-needs-auth-cache.json"
    cache.write_text(json.dumps(NEEDS_AUTH_CACHE), encoding="utf-8")
    record: list[httpx.Request] = []

    prepared = _prepare(device_state, repo, _platform(record))

    assert json.loads(cache.read_text(encoding="utf-8")) == {
        "plugin:cloudflare:cloudflare-api": {"timestamp": 1795164655664}}  # another server's mark stays
    assert json.loads(_of(record, "/sessions/register")[0].content)["mcp_auth_cache_cleared"] is True
    servers = json.loads(Path(prepared.mcp_path).read_text(encoding="utf-8"))["mcpServers"]
    assert launch_settings.MCP_SERVER_NAME in servers

    record.clear()
    _prepare(device_state, repo, _platform(record))  # nothing to remove: the platform is not told so
    assert "mcp_auth_cache_cleared" not in json.loads(_of(record, "/sessions/register")[0].content)
