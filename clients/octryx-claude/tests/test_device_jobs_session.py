"""A device turn's session: credential, folder, restart, start-up, model, permission mode and effort."""

from __future__ import annotations

import asyncio
import types
from pathlib import Path

import pytest

from octryx_claude import device_state
from octryx_claude.device_sdk import SdkDriver
from octryx_claude.device_session import PreparedSession, SessionRefusedError
from tests.device_jobs_support import FakeDriver, Prepare, _fake_sdk, _manager, _offer, _settle

# --- the session of a turn ------------------------------------------------------------------------------------


def _control_plane(record, *, policy_state="allowed", seat_refused="", models=None):
    import httpx

    def handler(request):
        record.append(request)
        path = request.url.path
        if path.endswith("/client-policy"):
            body = {"state": policy_state}
            if seat_refused:
                body["seat"] = {"state": "forbidden", "reason": seat_refused}
            if models is not None:
                body["models"] = models
            return httpx.Response(200, json=body)
        if path.endswith("/sessions/register") or path.endswith("/sessions/hook-key"):
            return httpx.Response(200, json={"state": "registered"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_a_turn_session_uses_the_device_credential_and_fails_closed(short_state, monkeypatch):
    state = short_state
    import time as clock

    from octryx_claude import launch
    from octryx_claude.device_session import prepare_session
    from octryx_claude.tokens import GATEWAY_AUDIENCE

    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    state.with_credential_set("device").write_credentials({
        "base_url": "https://octryx.example.test", "client_id": "oec_test", "refresh_token": "device-refresh",
        "tokens": {GATEWAY_AUDIENCE: {"access_token": "device-gateway", "expires_at": clock.time() + 3600}}})
    record = []
    with _control_plane(record) as http:
        prepared = prepare_session(state, base_url="https://octryx.example.test", workspace_id="ws-1",
                                   profile="governed", folder=str(short_state.root), http=http,
                                   shim=Path("/bin/octryx-claude"))
    try:
        assert {request.headers["authorization"] for request in record} == {"Bearer device-gateway"}
        register = [request for request in record if request.url.path.endswith("/sessions/register")][0]
        assert b'"client": "octryx-claude-device"' in register.content.replace(b'":"', b'": "')
        assert prepared.env["OCTRYX_CREDENTIAL_SET"] == "device" and prepared.cli_path == "/usr/local/bin/claude"
        settings = prepared.settings_path.read_text()
        assert "disableBypassPermissionsMode" not in settings and "pre-tool-use" in settings
    finally:
        prepared.close()

    with _control_plane([], policy_state="denied") as http, pytest.raises(SessionRefusedError) as closed:
        prepare_session(state, base_url="https://octryx.example.test", workspace_id="ws-1", profile="governed",
                        folder=str(state.root), http=http, shim=Path("/bin/octryx-claude"))
    assert closed.value.code.startswith("client_policy_")


@pytest.mark.asyncio
async def test_a_folder_the_service_cannot_read_is_refused_before_claude_code_starts(state, tmp_path, monkeypatch):
    from octryx_claude import device_folder_access

    prepare = Prepare()
    manager, channel, repo = _manager(state, tmp_path, prepare=prepare)
    device = device_state.load_device(state)
    device_state.save_device(state, {**device, "os": "macos"})

    def blocked(path):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(device_folder_access.os, "scandir", blocked)
    await manager.handle("job_offer", _offer(repo))
    rejected = channel.of("job_rejected")[0]
    assert rejected["reason"] == "device_folder_not_accessible" and rejected["os"] == "macos"
    assert rejected["service_python"] and prepare.calls == [] and not manager.turns


@pytest.mark.asyncio
async def test_turns_left_by_a_restarted_service_are_reported_failed_once_connected(state, tmp_path):
    hold = asyncio.Event()
    manager, channel, repo = _manager(state, tmp_path, driver=FakeDriver(hold=hold))
    await manager.handle("job_offer", _offer(repo, job_id="dj_1", turn_id="t1"))
    await asyncio.sleep(0.05)
    assert manager.turns  # the service is killed here: the turn never finishes

    restarted, restarted_channel, _ = _manager(state, tmp_path)
    assert restarted_channel.sent == []
    await restarted.handle("connected", {"paused": False})
    assert restarted_channel.sent == [("dj_1", "turn_finished", {"turn_id": "t1", "status": "failed",
                                                                 "reason": "service_restarted"})]
    await restarted.handle("connected", {"paused": False})  # reported once
    assert len(restarted_channel.sent) == 1
    hold.set()
    await _settle(manager)


@pytest.mark.asyncio
async def test_claude_code_that_does_not_initialize_ends_the_turn_with_a_clear_code(state, tmp_path):
    class Hanging:
        def __init__(self, options):
            self.options = options

        async def __aenter__(self):
            raise Exception("Control request timeout: initialize")  # noqa: TRY002 - what the SDK raises

        async def __aexit__(self, *exc):
            return False

    sdk = _fake_sdk()
    sdk.ClaudeSDKClient = Hanging
    manager, channel, repo = _manager(state, tmp_path, driver=SdkDriver(sdk))
    await manager.handle("job_offer", _offer(repo))
    await _settle(manager)
    assert channel.of("turn_finished") == [{"turn_id": "t1", "status": "error", "error": "claude_initialize_timeout"}]


def test_a_requested_model_must_be_offered_by_the_sessions_client_policy(short_state, monkeypatch):
    import time as clock

    from octryx_claude import launch
    from octryx_claude.device_session import prepare_session
    from octryx_claude.tokens import GATEWAY_AUDIENCE

    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    short_state.with_credential_set("device").write_credentials({
        "base_url": "https://octryx.example.test", "client_id": "oec_test", "refresh_token": "device-refresh",
        "tokens": {GATEWAY_AUDIENCE: {"access_token": "device-gateway", "expires_at": clock.time() + 3600}}})
    models = {"governed": [{"id": "co-sonnet", "display_name": "Company Sonnet", "source": "company"}], "seat": []}
    record = []
    with _control_plane(record, models=models) as http, pytest.raises(SessionRefusedError) as refused:
        prepare_session(short_state, base_url="https://octryx.example.test", workspace_id="ws-1", profile="governed",
                        folder=str(short_state.root), model="claude-not-offered", http=http,
                        shim=Path("/bin/octryx-claude"))
    assert refused.value.code == "model_not_offered"
    assert not [request for request in record if request.url.path.endswith("/sessions/register")]
    with _control_plane([], models=models) as http:
        prepared = prepare_session(short_state, base_url="https://octryx.example.test", workspace_id="ws-1",
                                   profile="governed", folder=str(short_state.root), model="co-sonnet", http=http,
                                   shim=Path("/bin/octryx-claude"))
    try:
        assert prepared.model == "co-sonnet"
    finally:
        prepared.close()


@pytest.mark.asyncio
async def test_the_offered_model_reaches_the_session_and_a_malformed_one_is_rejected(state, tmp_path):
    prepare = Prepare()
    manager, channel, repo = _manager(state, tmp_path, prepare=prepare)
    await manager.handle("job_offer", _offer(repo, model="company/co-sonnet"))
    await _settle(manager)
    assert prepare.calls[0]["model"] == "company/co-sonnet"
    await manager.handle("job_offer", _offer(repo, turn_id="t2", model="bad model; rm -rf"))
    await _settle(manager)
    assert channel.of("job_rejected") == [{"turn_id": "t2", "reason": "model_invalid"}]


@pytest.mark.asyncio
async def test_the_chats_permission_mode_and_effort_reach_the_turn_and_nothing_else_does(state, tmp_path):
    # the phone chooses Claude Code's permission mode (bypass included) and effort per turn.
    seen = []

    class Recording(FakeDriver):
        async def run_turn(self, prepared, **kwargs):
            seen.append(dict(prepared.extra))
            return await super().run_turn(prepared, **kwargs)

    manager, channel, repo = _manager(state, tmp_path, driver=Recording())
    await manager.handle("job_offer", _offer(repo, permission_mode="bypassPermissions", effort="high"))
    await _settle(manager)
    assert seen[0]["permission_mode"] == "bypassPermissions" and seen[0]["effort"] == "high"
    await manager.handle("job_offer", _offer(repo, job_id="dj_2", turn_id="t2", permission_mode="yolo"))
    await manager.handle("job_offer", _offer(repo, job_id="dj_3", turn_id="t3", effort="infinite"))
    await _settle(manager)
    assert [body["reason"] for body in channel.of("job_rejected")] == ["turn_options_invalid"] * 2


def test_the_sdk_gets_the_mode_and_effort():
    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    prepared = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                               mcp_path=Path("m.json"), env={}, profile="seat",
                               extra={"permission_mode": "acceptEdits", "effort": "max"})
    SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=None, decide=None)
    assert (captured["permission_mode"], captured["effort"]) == ("acceptEdits", "max")
    plain = PreparedSession(session_key="k", cli_path="claude", settings_path=Path("s.json"),
                            mcp_path=Path("m.json"), env={}, profile="seat")
    SdkDriver(sdk=fake_sdk)._options(plain, cwd="/x", resume=None, decide=None)
    assert (captured["permission_mode"], captured["effort"]) == ("default", None)
