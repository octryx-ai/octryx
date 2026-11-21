"""``octryx-claude device …``: enable/disable/status/pause/folders/parallel and the OS service units.

Nothing is installed on the machine running the tests: the service managers get a fake runner and a temporary
HOME, and the platform is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import argparse
import json
import os
import stat

import httpx

from octryx_claude import device_cli, device_state
from octryx_claude.state import CREDENTIAL_SET_DEVICE, LocalState
from octryx_claude.tokens import DEVICE_AUDIENCE
from tests.conftest import BASE_URL
from tests.device_cli_support import FakeManager, no_service_probe  # noqa: F401


def _configured(state: LocalState) -> LocalState:
    state.write_config({"base_url": BASE_URL})
    return state


def _enable_args(folders, **overrides) -> argparse.Namespace:
    values = {"name": "Build box", "folder": folders, "parallel": 4, "no_service": False, **overrides}
    return argparse.Namespace(**values)


def _platform(record: list[httpx.Request], *, register_status: int = 201):
    def handler(request: httpx.Request) -> httpx.Response:
        record.append(request)
        if request.url.path == "/api/v1/devices":
            if register_status != 201:
                return httpx.Response(register_status, json={"state": "denied", "reason": "device_name_taken"})
            return httpx.Response(201, json={
                "state": "registered", "device": {"id": "dev_0123456789abcdef"},
                "credential": {"refresh_token": "device-refresh-1", "client_id": "oec_test",
                               "scopes": ["device:connect", "model:invoke"], "audience": DEVICE_AUDIENCE}})
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "device-access", "refresh_token": "device-refresh-2",
                                             "expires_in": 900, "scope": "device:connect"})
        if request.url.path == "/api/v1/devices/self/disable":
            return httpx.Response(200, json={"state": "revoked"})
        return httpx.Response(404)

    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


def test_enable_registers_stores_a_separate_device_credential_and_installs_the_service(state, tmp_path):
    _configured(state)
    folder = tmp_path / "repo"
    folder.mkdir()
    record: list[httpx.Request] = []
    manager = FakeManager()
    code = device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=_platform(record), manager=manager,
                                 os_name="linux")
    assert code == 0
    body = json.loads(record[0].content)
    assert record[0].headers["authorization"] == "Bearer gw-cached"  # the user's own gateway login
    assert body["folders"] == [str(folder.resolve())] and body["os"] == "linux" and body["max_parallel_jobs"] == 4
    assert body["profiles_available"] == ["governed"] and len(body["public_key"]) == 43
    assert manager.calls == ["install"]

    device_creds = state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()
    assert device_creds["refresh_token"] == "device-refresh-1"
    assert state.credentials()["refresh_token"] == "refresh-1"  # the login stays untouched
    assert stat.S_IMODE(os.stat(state.root / "device-key.pem").st_mode) == 0o600
    assert device_state.load_device(state)["device_id"] == "dev_0123456789abcdef"
    # Run again: no second registration; new folders join and the unit is rewritten and reloaded.
    other = tmp_path / "other"
    other.mkdir()
    again: list[httpx.Request] = []
    assert device_cli.run_enable(_enable_args([str(folder), str(other)]), state, http_factory=_platform(again),
                                 manager=manager, os_name="linux") == 0
    assert again == [] and manager.calls == ["install", "install"]
    assert device_state.load_device(state)["folders"] == [str(folder.resolve()), str(other.resolve())]
    device_state.write_status(state, {"running_jobs": 1})
    assert device_cli.run_enable(_enable_args([]), state, manager=manager, os_name="linux") == 0
    assert manager.calls == ["install", "install"]  # never reloaded under a running job


def test_enable_refusals_leave_no_key_and_name_the_code(state, tmp_path, capsys):
    folder = tmp_path / "repo"
    folder.mkdir()
    assert device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=_platform([]),
                                 manager=FakeManager(), os_name="linux") == 2
    assert "not_logged_in" in capsys.readouterr().err
    _configured(state)
    assert device_cli.run_enable(_enable_args([str(tmp_path / "missing")]), state, http_factory=_platform([]),
                                 manager=FakeManager(), os_name="linux") == 2
    assert "folder_not_found" in capsys.readouterr().err
    assert device_cli.run_enable(_enable_args([str(folder)], parallel=9), state, http_factory=_platform([]),
                                 manager=FakeManager(), os_name="linux") == 2
    assert device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=_platform([], register_status=400),
                                 manager=FakeManager(), os_name="linux") == 2
    err = capsys.readouterr().err
    assert "denied/device_name_taken" in err and "device-refresh" not in err
    assert not (state.root / "device-key.pem").exists()
    assert not device_state.load_device(state)


def test_disable_removes_the_service_revokes_with_the_device_token_and_keeps_the_login(state, tmp_path):
    _configured(state)
    folder = tmp_path / "repo"
    folder.mkdir()
    device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=_platform([]), manager=FakeManager(),
                          os_name="linux")
    record: list[httpx.Request] = []
    manager = FakeManager()
    assert device_cli.run_disable(state, http_factory=_platform(record), manager=manager) == 0
    assert manager.calls == ["uninstall"]
    token_form = dict(httpx.QueryParams(record[0].content.decode()))
    assert token_form["refresh_token"] == "device-refresh-1" and token_form["resource"] == DEVICE_AUDIENCE
    assert record[1].url.path == "/api/v1/devices/self/disable"
    assert record[1].headers["authorization"] == "Bearer device-access"
    assert not (state.root / "device-key.pem").exists()
    assert not (state.root / "device-credentials.json").exists()
    assert state.credentials()["refresh_token"] == "refresh-1"


def test_a_lost_answer_keeps_the_key_and_the_retry_proves_it_is_the_same_device(state, tmp_path, capsys):
    """Demo cold run: the platform registered the device, the answer timed out, the launcher forgot its
    key, and the retry met its own entry as device_name_taken. Now the key and a pending marker are stored before
    the request; the retry sends the same key with a proof the platform can check."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    _configured(state)
    folder = tmp_path / "repo"
    folder.mkdir()
    sent: list[httpx.Request] = []

    def timing_out():
        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            raise httpx.ReadTimeout("slow answer", request=request)
        return httpx.Client(transport=httpx.MockTransport(handler))

    assert device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=timing_out,
                                 manager=FakeManager(), os_name="linux") == 2
    assert "platform_unreachable" in capsys.readouterr().err
    assert (state.root / "device-key.pem").exists()
    assert device_state.load_device(state)["pending"]["name"] == "Build box"
    record: list[httpx.Request] = []
    assert device_cli.run_enable(_enable_args([str(folder)]), state, http_factory=_platform(record),
                                 manager=FakeManager(), os_name="linux") == 0
    first, retry = json.loads(sent[0].content), json.loads(record[0].content)
    assert retry["public_key"] == first["public_key"]
    key = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(retry["public_key"] + "="))
    key.verify(base64.urlsafe_b64decode(retry["key_proof"] + "=" * (-len(retry["key_proof"]) % 4)),
               device_state.registration_payload("Build box", retry["public_key"]))
    assert device_state.load_device(state)["device_id"] == "dev_0123456789abcdef"
    assert "pending" not in device_state.load_device(state)
