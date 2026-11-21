"""The headless runner in a platform sandbox: inputs checked, enrollment like a device registration, the clone with
the token only in git's environment, the person-level parts off, and the end when idle."""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import httpx
import pytest

from octryx_claude import device_state, launch_settings, sandbox, sandbox_serve
from octryx_claude.state import CREDENTIAL_SET_DEVICE, LocalState

ENV = {"OCTRYX_BASE_URL": "https://octryx.example.test/", "OCTRYX_SANDBOX_RUN_ID": "run_123",
       "OCTRYX_SANDBOX_BRANCH": "master", "OCTRYX_TOOLCHAIN": "python"}
GATEWAY = "http://octryx-git-gateway:8080/git/run_123/repo_9.git"
TOKEN = "fake-enroll-token-0123456789"
GIT = "fake-git-token-0123456789abcdef"


def test_inputs_are_checked():
    config = sandbox.settings(ENV)
    assert config["base_url"] == "https://octryx.example.test" and config["workspace"] == "/workspace"
    for key, value, code in (("OCTRYX_BASE_URL", "http://octryx.example.test", "base_url_not_https"),
                             ("OCTRYX_SANDBOX_RUN_ID", "../x", "run_id_invalid"),
                             ("OCTRYX_SANDBOX_BRANCH", "--upload-pack=x", "branch_invalid")):
        with pytest.raises(sandbox.SandboxError) as error:
            sandbox.settings({**ENV, key: value})
        assert error.value.code == code


def test_enrollment_stores_the_device_like_a_registration(tmp_path):
    secret = tmp_path / "enroll"
    secret.write_text(TOKEN + "\n")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(201, json={"credential": {"refresh_token": "fake-refresh", "client_id": "octryx-device",
                                                        "scopes": ["device"]}, "device": {"id": "dev_sbx1"}})

    state = LocalState(tmp_path / "state")
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert sandbox.enroll(state, sandbox.settings(ENV), http=http, token_file=secret) == "dev_sbx1"
    assert seen["path"] == sandbox.ENROLL_PATH
    body = seen["body"]
    assert body["token"] == TOKEN and body["run_id"] == "run_123" and body["service_kind"] == "sandbox"
    assert body["folders"] == ["/workspace"] and body["profiles_available"] == ["governed"]
    assert body["max_parallel_jobs"] == 1 and body["public_key"]
    creds = state.with_credential_set(CREDENTIAL_SET_DEVICE).credentials()
    assert creds["refresh_token"] == "fake-refresh" and creds["base_url"] == "https://octryx.example.test"
    device = device_state.load_device(state)
    assert device["device_id"] == "dev_sbx1" and device["folders"] == ["/workspace"]
    assert device["sandbox_run_id"] == "run_123"
    assert sandbox_serve.report(state)["live"] is False and sandbox_serve.report(state)["service_kind"] == "sandbox"


@pytest.mark.parametrize(("status", "payload", "code"), [
    (403, {}, "enroll_refused_403"),
    (201, {"device": {"id": "x"}}, "enroll_answer_invalid"),
])
def test_a_refused_or_odd_enrollment_stops_the_sandbox(tmp_path, status, payload, code):
    secret = tmp_path / "enroll"
    secret.write_text(TOKEN)
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    with httpx.Client(transport=transport) as http, pytest.raises(sandbox.SandboxError) as error:
        sandbox.enroll(LocalState(tmp_path / "s"), sandbox.settings(ENV), http=http, token_file=secret)
    assert error.value.code == code
    with httpx.Client(transport=transport) as http, pytest.raises(sandbox.SandboxError) as missing:
        sandbox.enroll(LocalState(tmp_path / "t"), sandbox.settings(ENV), http=http, token_file=tmp_path / "none")
    assert missing.value.code == "enroll_token_missing"


def test_the_sandbox_ends_when_idle_or_when_no_job_comes():
    def run(script, **limits):
        """``script``: (time, busy) per round of the watcher; the last entry repeats."""
        steps = iter(script)
        current = {"busy": False}

        def clock():
            now, busy = next(steps, script[-1])
            current["busy"] = busy
            return now

        class Manager:
            @property
            def turns(self):
                return {"t": 1} if current["busy"] else {}

        stop = asyncio.Event()
        reason = asyncio.run(sandbox_serve.idle_watch(Manager(), stop, clock=clock, poll=0.001, **limits))
        return reason, stop.is_set()

    # start, a turn runs, it ends, then 300 s idle
    assert run([(0, False), (10, True), (20, False), (200, False), (330, False)], idle_exit=300) == ("idle", True)
    # never a job within first_job
    assert run([(0, False), (500, False), (950, False)], first_job=900) == ("no_job", True)
    # still working at 2000 s: not ended yet (the stop is the caller's)
    stop_after = [(0, False), (10, True), (2000, True)]
    assert run(stop_after + [(2010, False), (2400, False)], idle_exit=300) == ("idle", True)


def test_a_maven_mirror_is_written_only_for_https(tmp_path):
    assert sandbox.maven_mirror({"MAVEN_MIRROR": "http://nexus"}, tmp_path) is None
    path = sandbox.maven_mirror({"MAVEN_MIRROR": "https://nexus.example.test/maven"}, tmp_path)
    assert path == tmp_path / ".m2" / "settings.xml" and "https://nexus.example.test/maven" in path.read_text()


def test_the_agent_never_reads_the_sandbox_secrets(tmp_path, monkeypatch):

    monkeypatch.setenv("OCTRYX_SANDBOX_RUN_ID", "run_123")
    settings = launch_settings.build_settings(shim=Path("/bin/true"), state_root=tmp_path, env={}, policy={},
                                     base_url="https://octryx.example.test")
    deny = settings["permissions"]["deny"]
    assert "Read(//run/secrets/**)" in deny and "Edit(//run/secrets/**)" in deny
    monkeypatch.delenv("OCTRYX_SANDBOX_RUN_ID")
    plain = launch_settings.build_settings(shim=Path("/bin/true"), state_root=tmp_path, env={}, policy={},
                                  base_url="https://octryx.example.test")
    assert "Read(//run/secrets/**)" not in plain["permissions"]["deny"]


def _enrolled(tmp_path) -> LocalState:
    state = LocalState(tmp_path / "state")
    device_state.save_device(state, {"device_id": "dev_sbx1", "base_url": "https://octryx.example.test",
                                     "sandbox_run_id": "run_123", "folders": ["/workspace"]})
    return state


def _gateway(monkeypatch, answer=None, status=200):
    from octryx_claude import tokens

    monkeypatch.setattr(tokens, "get_access_token", lambda state, audience, http: f"device-access-for-{audience}")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content), request.headers.get("authorization")))
        return httpx.Response(status, json=answer if answer is not None else {
            "token": "fake-gateway-jwt-abc", "expires_at": "2026-11-13T10:10:00Z", "url": GATEWAY})

    return seen, lambda **_k: httpx.Client(transport=httpx.MockTransport(handler))


def test_a_gateway_token_is_minted_for_the_run_with_the_device_credential(tmp_path, monkeypatch):
    seen, client = _gateway(monkeypatch)
    with client() as http:
        minted = sandbox.git_token(_enrolled(tmp_path), http=http)
    assert minted == {"token": "fake-gateway-jwt-abc", "url": GATEWAY, "expires_at": "2026-11-13T10:10:00Z"}
    [(path, body, auth)] = seen
    assert path == sandbox.GIT_TOKEN_PATH and body == {"run_id": "run_123"} and auth.startswith("Bearer device-")
    for odd in ({"token": "a b", "url": GATEWAY}, {"token": "t", "url": "ftp://x"},
                {"token": "t", "url": "https://user:pw@gw/x.git"}, {"url": GATEWAY}):
        _seen, client = _gateway(monkeypatch, answer=odd)
        with client() as http, pytest.raises(sandbox.SandboxError) as error:
            sandbox.git_token(_enrolled(tmp_path), http=http)
        assert error.value.code == "git_token_invalid", odd
    _seen, client = _gateway(monkeypatch, status=403)
    with client() as http, pytest.raises(sandbox.SandboxError) as error:
        sandbox.git_token(_enrolled(tmp_path), http=http)
    assert error.value.code == "git_token_refused_403"
    with client() as http, pytest.raises(sandbox.SandboxError) as error:
        sandbox.git_token(LocalState(tmp_path / "none"), http=http)
    assert error.value.code == "not_enrolled"


def test_the_credential_helper_answers_only_the_gateway_and_stores_nothing(tmp_path, monkeypatch):
    import io

    _seen, client = _gateway(monkeypatch)
    state = _enrolled(tmp_path)
    out = io.StringIO()
    asked = "protocol=http\nhost=octryx-git-gateway:8080\npath=git/run_123/repo_9.git\n\n"
    assert sandbox.credential_helper("get", io.StringIO(asked), out, state=state, http_factory=client) == 0
    assert out.getvalue() == "username=x-run\npassword=fake-gateway-jwt-abc\n"
    other = io.StringIO()
    assert sandbox.credential_helper("get", io.StringIO("protocol=https\nhost=github.com\n\n"), other,
                                     state=state, http_factory=client) == 0
    assert other.getvalue() == ""  # another host gets nothing
    for partial in ("host=octryx-git-gateway:8080\n\n", "protocol=http\n\n", "\n",
                    "protocol=https\nhost=octryx-git-gateway:8080\n\n",
                    "protocol=http\nhost=octryx-git-gateway\n\n"):
        none = io.StringIO()
        assert sandbox.credential_helper("get", io.StringIO(partial), none, state=state, http_factory=client) == 0
        assert none.getvalue() == "", partial  # Protocol and host must both match the gateway exactly
    for action in ("store", "erase"):
        silent = io.StringIO()
        assert sandbox.credential_helper(action, io.StringIO(asked + "password=x\n"), silent, state=state,
                                         http_factory=client) == 0
        assert silent.getvalue() == ""
    _seen, refusing = _gateway(monkeypatch, status=403)
    assert sandbox.credential_helper("get", io.StringIO(asked), io.StringIO(), state=state,
                                     http_factory=refusing) == 1


def test_git_inherits_only_the_allowlisted_environment():
    env = sandbox.git_env({"PATH": "/usr/bin", "HOME": "/tmp/home", "OCTRYX_CLAUDE_HOME": "/tmp/octryx",
                           "AWS_SECRET_ACCESS_KEY": "s", "OCTRYX_ENROLL_TOKEN": "t", "GIT_ASKPASS": "/x",
                           "https_proxy": "http://proxy:3128"})
    assert env == {"PATH": "/usr/bin", "HOME": "/tmp/home", "OCTRYX_CLAUDE_HOME": "/tmp/octryx",
                   "https_proxy": "http://proxy:3128", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}


def test_the_checkout_clones_from_the_gateway_and_writes_no_secret(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sandbox, "git_token", lambda state, http: {"token": "fake-gateway-jwt-abc", "url": GATEWAY,
                                                                   "expires_at": ""})

    def run(argv, **kwargs):
        calls.append(argv)
        return types.SimpleNamespace(returncode=0)

    config = {**sandbox.settings(ENV), "workspace": str(tmp_path / "ws")}
    assert sandbox.checkout(_enrolled(tmp_path), config, http=None, run=run) == "octryx-run/run_123"
    clone = calls[0]
    assert clone[:5] == ["git", "-c", "credential.helper=", "-c", f"credential.helper={sandbox.HELPER}"]
    assert clone[-2:] == [GATEWAY, str(tmp_path / "ws")] and "--branch" in clone
    assert not any("fake-gateway-jwt" in part for argv in calls for part in argv)  # never on a command line
    assert calls[-1][-3:] == ["checkout", "-b", "octryx-run/run_123"]
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "ws" / "x").write_text("x")
    with pytest.raises(sandbox.SandboxError) as error:
        sandbox.checkout(_enrolled(tmp_path), config, http=None, run=run)
    assert error.value.code == "workspace_not_empty"


def test_a_real_clone_leaves_only_the_helper_in_the_config(tmp_path, monkeypatch):
    import subprocess

    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "master", str(origin)], check=True)
    (origin / "README.md").write_text("hi")
    for argv in (["add", "."], ["commit", "-qm", "c"]):
        subprocess.run(["git", "-C", str(origin), "-c", "user.email=a@b", "-c", "user.name=a", *argv], check=True)
    monkeypatch.setattr(sandbox, "git_token", lambda state, http: {"token": "fake-gateway-jwt-abc",
                                                                   "url": str(origin), "expires_at": ""})
    workspace = tmp_path / "ws"
    config = {**sandbox.settings(ENV), "workspace": str(workspace)}
    assert sandbox.checkout(_enrolled(tmp_path), config, http=None) == "octryx-run/run_123"
    text = (workspace / ".git" / "config").read_text()
    assert "fake-gateway-jwt" not in text and "octryx-claude git-credential" in text
    head = subprocess.run(["git", "-C", str(workspace), "branch", "--show-current"], capture_output=True, text=True)
    assert head.stdout.strip() == "octryx-run/run_123"

