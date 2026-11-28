from __future__ import annotations

import asyncio
import json
import os
import stat

import httpx
import pytest

from octryx_claude import codex_config, device_state, runner, token_broker, tokens
from octryx_claude.state import CREDENTIAL_SET_DEVICE, LocalState
from tests.codex_driver_support import _prepared


def _platform(seen: list):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content or b"{}") if request.method == "POST" else {}))
        if request.url.path == "/oauth/register":
            return httpx.Response(201, json={"client_id": "client-1"})
        if request.url.path == runner.ENROLL_PATH:
            credential = {"refresh_token": "refresh-1", "scopes": ["device:connect"]}
            return httpx.Response(201, json={"device": {"id": "dev_runner1"}, "credential": credential})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_a_runner_enrolls_once_with_the_join_secret_and_keeps_its_credential_private(tmp_path):
    secret = tmp_path / "runner-join"
    secret.write_text("join-secret-value\n")
    state = LocalState(tmp_path / "state").ensure()
    seen: list = []
    with _platform(seen) as http:
        assert runner.enroll(state, "https://platform.test", http=http, secret_file=secret) == "dev_runner1"
    path, body = seen[-1]
    assert path == runner.ENROLL_PATH and body["join_secret"] == "join-secret-value" and body["client_id"] == "client-1"
    assert body["public_key"] and "join-secret" not in json.dumps(device_state.load_device(state))
    device = device_state.load_device(state)
    assert device["runner"] is True and device["folders"] == ["/workspace"]
    credentials = state.with_credential_set(CREDENTIAL_SET_DEVICE)
    assert credentials.credentials()["refresh_token"] == "refresh-1"
    assert stat.S_IMODE(credentials.credentials_path.stat().st_mode) == 0o600


def test_a_runner_reports_its_runtime_and_names_the_platforms_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.RUNTIME_ENV, "runsc")
    secret = tmp_path / "runner-join"
    secret.write_text("join-secret-value")
    seen: list = []
    with _platform(seen) as http:
        runner.enroll(LocalState(tmp_path / "a").ensure(), "https://platform.test", http=http, secret_file=secret)
    assert seen[-1][1]["runtime"] == "runsc"

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/register":
            return httpx.Response(201, json={"client_id": "client-1"})
        return httpx.Response(409, json={"state": "denied", "reason": "runner_runtime_mismatch"})

    with httpx.Client(transport=httpx.MockTransport(refuse)) as http, pytest.raises(runner.RunnerError) as refused:
        runner.enroll(LocalState(tmp_path / "b").ensure(), "https://platform.test", http=http, secret_file=secret)
    assert refused.value.code == "runner_runtime_mismatch"


def test_a_runner_without_a_join_secret_does_not_start(tmp_path):
    state = LocalState(tmp_path / "state").ensure()
    with _platform([]) as http, pytest.raises(runner.RunnerError) as refused:
        runner.enroll(state, "https://platform.test", http=http, secret_file=tmp_path / "missing")
    assert refused.value.code == "runner_join_secret_missing"


def test_shared_state_opens_files_to_the_group_but_never_the_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTRYX_SHARED_STATE", "1")
    state = LocalState(tmp_path / "state").ensure()
    state.write_config({"x": 1})
    state.with_credential_set(CREDENTIAL_SET_DEVICE).write_credentials({"refresh_token": "r"})
    assert stat.S_IMODE(state.config_path.stat().st_mode) == 0o660
    assert stat.S_IMODE(state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.session_dir("00000000-0000-4000-8000-000000000001").stat().st_mode) == 0o2770


def test_the_token_broker_hands_out_gateway_and_mcp_tokens_only(tmp_path, monkeypatch):
    import tempfile
    from pathlib import Path

    monkeypatch.setattr(tokens, "get_access_token", lambda state, audience, http: f"token-for-{audience}")
    path = Path(tempfile.mkdtemp(dir="/tmp")) / "token.sock"  # a Unix socket path is short (104 bytes on macOS)

    async def scenario():
        stop = asyncio.Event()
        server = asyncio.create_task(token_broker.serve(LocalState(tmp_path / "state"), path, stop))
        for _ in range(500):
            if path.exists() or server.done():
                break
            await asyncio.sleep(0.01)
        assert path.exists(), server
        answers = {}
        for audience in (tokens.GATEWAY_AUDIENCE, tokens.MCP_AUDIENCE, tokens.DEVICE_AUDIENCE):
            try:
                answers[audience] = await asyncio.to_thread(token_broker.request_token, audience, str(path))
            except tokens.TokenUnavailableError as exc:
                answers[audience] = exc.code
        mode = stat.S_IMODE(path.stat().st_mode)
        stop.set()
        await server
        return answers, mode

    answers, mode = asyncio.run(scenario())
    assert answers[tokens.GATEWAY_AUDIENCE] == f"token-for-{tokens.GATEWAY_AUDIENCE}"
    assert answers[tokens.MCP_AUDIENCE] == f"token-for-{tokens.MCP_AUDIENCE}"
    assert answers[tokens.DEVICE_AUDIENCE] == "audience_not_allowed"  # never the device channel's token
    assert mode == 0o660


def test_a_process_with_the_broker_never_reads_the_credential_file(tmp_path, monkeypatch):
    monkeypatch.setenv(token_broker.SOCKET_ENV, str(tmp_path / "token.sock"))
    asked: list = []
    monkeypatch.setattr(token_broker, "request_token", lambda audience, path: asked.append((audience, path)) or "t")
    state = LocalState(tmp_path / "nowhere")  # no credentials at all
    with httpx.Client() as http:
        assert tokens.get_access_token(state, tokens.GATEWAY_AUDIENCE, http=http) == "t"
    assert asked == [(tokens.GATEWAY_AUDIENCE, str(tmp_path / "token.sock"))]


def test_under_an_agent_account_codex_runs_as_it_and_cannot_change_its_config(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.AGENT_UID_ENV, "10002")
    assert runner.agent_command()[:3] == ["setpriv", "--reuid=10002", "--regid=10002"]
    assert "--bounding-set=-all" in runner.agent_command() and runner.agent_command()[-1] == "--"
    prepared = _prepared(tmp_path, OCTRYX_CLAUDE_HOME=str(tmp_path / "state"))
    home = codex_config.prepare_home(prepared, sandboxed=False, device_turn=True)
    assert home.parent == tmp_path / "state" / codex_config.CODEX_HOMES_DIR  # outside the session folder
    assert stat.S_IMODE(home.parent.stat().st_mode) == 0o2750
    assert stat.S_IMODE(home.stat().st_mode) == 0o3770  # Codex adds files, never replaces the launcher's
    assert stat.S_IMODE((home / "config.toml").stat().st_mode) == 0o644
    assert stat.S_IMODE((home / codex_config.ENV_WRAPPER).stat().st_mode) == 0o755
    env = codex_config.environment(prepared, home)
    assert env[token_broker.SOCKET_ENV] == str(tmp_path / "state" / runner.BROKER_SOCKET)
    assert env["HOME"] == runner.AGENT_HOME
    assert f"OCTRYX_TOKEN_SOCKET={tmp_path / 'state' / runner.BROKER_SOCKET}" in (
        home / codex_config.ENV_WRAPPER).read_text()


def test_outside_a_runner_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.AGENT_UID_ENV, raising=False)
    assert runner.agent_command() == []
    home = codex_config.prepare_home(_prepared(tmp_path), sandboxed=False, device_turn=True)
    assert home == tmp_path / "sessions" / "k1" / codex_config.HOME_DIR


def test_a_runner_makes_the_folder_the_platform_names_for_a_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "WORKSPACE_ROOT", str(tmp_path))
    runner.ensure_job_folder(str(tmp_path / "abc123"))
    assert stat.S_IMODE((tmp_path / "abc123").stat().st_mode) == 0o2770
    runner.ensure_job_folder(str(tmp_path / "deeper" / "x"))  # only a folder right under the workspace
    assert not (tmp_path / "deeper").exists()
    assert os.access(tmp_path / "abc123", os.W_OK)


def test_behind_a_container_ask_before_changes_is_codex_asking_before_every_change(tmp_path, monkeypatch):
    monkeypatch.setenv(codex_config.CONTAINER_BOUNDARY_ENV, "1")
    asking = _prepared(tmp_path)
    asking.extra["permission_mode"] = codex_config.ASK_BEFORE_CHANGES
    assert codex_config.thread_approval(asking) == "untrusted"
    home = codex_config.prepare_home(asking, sandboxed=True, device_turn=True)
    assert 'approval_policy = "on-request"' in (home / "config.toml").read_text()  # Codex refuses it in the file
    editing = _prepared(tmp_path / "edits")
    editing.extra["permission_mode"] = "acceptEdits"
    assert codex_config.thread_approval(editing) == "on-request"
    monkeypatch.delenv(codex_config.CONTAINER_BOUNDARY_ENV)
    assert codex_config.thread_approval(asking) == "on-request"  # a sandbox asks on its own


def test_a_runner_empties_itself_before_the_next_person_or_workspace(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.AGENT_UID_ENV, raising=False)
    state = LocalState(tmp_path / "state").ensure()
    roots = [tmp_path / "workspace", tmp_path / "agent-home", state.root / "codex-threads"]
    for root in roots:
        (root / "thread" / "deep").mkdir(parents=True)
        (root / "thread" / "deep" / "private.txt").write_text("A's data")
    offer = {"owner_user_id": "person-a", "workspace_id": "ws-1", "resume_session_id": "t-1"}
    assert runner.admit_tenant(state, offer, busy=False, roots=roots)
    assert all(not any(root.iterdir()) for root in roots)  # nothing known about the last turn: emptied

    (roots[0] / "a-folder").mkdir()
    same = {"owner_user_id": "person-a", "workspace_id": "ws-1", "resume_session_id": "t-1"}
    assert runner.admit_tenant(state, same, busy=True, roots=roots)
    assert (roots[0] / "a-folder").exists() and same["resume_session_id"] == "t-1"  # the thread stays

    other = {"owner_user_id": "person-b", "workspace_id": "ws-1", "resume_session_id": "t-9"}
    assert not runner.admit_tenant(state, other, busy=True, roots=roots)  # never beside A's running turn
    assert (roots[0] / "a-folder").exists()
    assert runner.admit_tenant(state, other, busy=False, roots=roots)
    assert not any(roots[0].iterdir()) and "resume_session_id" not in other
    assert runner.admit_tenant(state, {"owner_user_id": "person-b", "workspace_id": "ws-2"}, busy=False, roots=roots)
    assert (state.root / runner.TENANT_FILE).read_text() == "person-b/ws-2"
