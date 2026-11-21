"""Claude Code profiles outside octryx (P6b/P6c, Alice), client side.

- discovery finds ``~/.claude``, ``~/.claude-*`` and shell-assigned config dirs, never octryx's own;
- nothing is read before the person connects a profile; names are short and unique;
- the report lists the connected profiles' recent sessions with folder, redacted title and last answer;
- ``~/.claude`` is reached by unsetting ``CLAUDE_CONFIG_DIR``; no platform credential reaches the profile;
- a take-over offer runs only for a connected profile, only the session it resumes as it exists there, only in the
  folder that session ran in, without octryx's settings, gateway or strict MCP config.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from octryx_claude import local_profiles
from octryx_claude.device_jobs import JobManager
from octryx_claude.device_sdk import SdkDriver
from octryx_claude.device_session import prepare_local
from tests.device_jobs_support import FakeChannel, FakeDriver, NoHttp, _settle

SID = "0b4e2c9a-7f1d-4c3b-9a8e-112233445566"


def _profile(home: Path, name: str, sessions: dict[str, tuple[str, str]] | None = None) -> Path:
    root = home / name
    (root / "projects").mkdir(parents=True)
    for session_id, (cwd, prompt) in (sessions or {}).items():
        folder = root / "projects" / cwd.strip("/").replace("/", "-")
        folder.mkdir(exist_ok=True)
        (folder / f"{session_id}.jsonl").write_text("\n".join(json.dumps(entry) for entry in [
            {"type": "user", "cwd": cwd, "message": {"role": "user", "content": prompt}},
            {"type": "assistant", "cwd": cwd, "message": {"content": [{"type": "text", "text": "Done, token=ghp_"
                                                                        + "a" * 36}]}},
        ]) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_discovery_finds_the_profiles_and_never_octryx_own(state, home):
    _profile(home, ".claude")
    _profile(home, ".claude-private")
    elsewhere = _profile(home, "work/claude-cfg")
    (home / ".claude-empty").mkdir()  # no projects folder: no profile
    (home / ".zshrc").write_text(f'claude-x() {{ CLAUDE_CONFIG_DIR="{elsewhere}" command claude "$@"; }}\n')
    found = local_profiles.discover(state, home=home)
    assert found == [(home / ".claude").resolve(), (home / ".claude-private").resolve(), elsewhere.resolve()]
    assert all(not str(path).startswith(str(state.root)) for path in found)
    assert local_profiles.suggested_name(found[0]) == "default" and local_profiles.suggested_name(found[1]) == "private"


def test_connect_names_and_disconnect(state, home):
    team = _profile(home, ".claude")
    with pytest.raises(local_profiles.ProfileError):
        local_profiles.connect(state, home / "nothing")
    with pytest.raises(local_profiles.ProfileError):
        local_profiles.connect(state, team, name="Way Too Long")
    with pytest.raises(local_profiles.ProfileError):
        local_profiles.connect(state, state.root)  # octryx's own
    assert local_profiles.connect(state, "~/.claude", name="team").config_dir == team.resolve()
    with pytest.raises(local_profiles.ProfileError):
        local_profiles.connect(state, _profile(home, ".claude-other"), name="team")
    assert [profile.name for profile in local_profiles.connected(state)] == ["team"]
    assert local_profiles.disconnect(state, "team") and local_profiles.connected(state) == []


def test_only_connected_profiles_are_reported_with_redacted_texts(state, home):
    _profile(home, ".claude", {SID: ("/Users/dev/PRIV", "Build the mobile app\nwith tests")})
    _profile(home, ".claude-private", {"1a2b3c4d-1111-2222-3333-444455556666": ("/Users/dev/x", "secret plans")})
    (home / ".claude" / "projects" / "Users-dev-PRIV" / "not-a-session.jsonl").write_text("{}\n")
    assert local_profiles.report(state) == {"profiles": [], "takeover_profiles": [], "sessions": []}  # nothing yet
    local_profiles.connect(state, home / ".claude", name="team")
    report = local_profiles.report(state)
    assert report["profiles"] == ["team"] and report["takeover_profiles"] == []
    [entry] = report["sessions"]
    assert (entry["profile"], entry["session_id"], entry["cwd"]) == ("team", SID, "/Users/dev/PRIV")
    assert entry["title"] == "Build the mobile app" and "ghp_" not in entry["last_text"]
    assert local_profiles.session_folder(local_profiles.find(state, "team"), SID) == "/Users/dev/PRIV"
    assert local_profiles.session_folder(local_profiles.find(state, "team"), "../../etc/passwd") == ""


def test_the_default_profile_is_reached_by_unsetting_the_config_dir(state, home):
    team = local_profiles.connect(state, _profile(home, ".claude"), name="team")
    private = local_profiles.connect(state, _profile(home, ".claude-private"), name="private")
    base = {"CLAUDE_CONFIG_DIR": "/somewhere", "ANTHROPIC_BASE_URL": "https://gateway", "ANTHROPIC_AUTH_TOKEN": "t",
            "PATH": "/bin"}
    assert local_profiles.profile_env(team, base) == {"PATH": "/bin"}
    assert local_profiles.profile_env(private, base) == {"PATH": "/bin", "CLAUDE_CONFIG_DIR": str(private.config_dir)}


def _local_manager(state, driver):
    manager = JobManager(state, driver_factory=lambda: driver, http_factory=NoHttp, shim=Path("/bin/true"),
                         prepare=lambda *_args, **_kwargs: pytest.fail("octryx's own session must not be prepared"))
    channel = FakeChannel()
    manager.attach(channel)
    return manager, channel


@pytest.mark.asyncio
async def test_a_take_over_runs_only_that_session_in_its_own_folder(state, home, tmp_path, monkeypatch):
    from octryx_claude import device_state, launch

    repo = tmp_path / "repo"
    repo.mkdir()
    _profile(home, ".claude", {SID: (str(repo), "Refactor")})
    local_profiles.connect(state, home / ".claude", name="team")  # shown, but no take-over
    device_state.save_device(state, {"device_id": "dev_x", "name": "Mac", "os": "darwin",
                                     "base_url": "https://octryx.example.test", "folders": [], "max_parallel_jobs": 4})
    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    driver = FakeDriver()
    manager, channel = _local_manager(state, driver)
    notified = []
    import octryx_claude.device_job_run as device_job_run

    monkeypatch.setattr(device_job_run, "notify_takeover", lambda profile, folder: notified.append((profile, folder)))

    def offer(turn, **extra):
        return {"job_id": f"dj_{turn}", "turn_id": f"t{turn}", "prompt": "Weiter", "folder": str(repo),
                "profile": "local:team", "workspace_id": "ws-private", "resume_session_id": SID,
                "limits": {"approval_timeout_s": 1}, **extra}

    await manager.handle("job_offer", offer(0))
    await _settle(manager)
    assert channel.of("job_rejected")[-1]["reason"] == "takeover_not_allowed_on_device"
    local_profiles.connect(state, home / ".claude", name="team", allow_takeover=True)
    await manager.handle("job_offer", offer(1, profile="local:other"))
    await manager.handle("job_offer", offer(2, resume_session_id="1a2b3c4d-1111-2222-3333-444455556666"))
    await manager.handle("job_offer", offer(3, folder=str(tmp_path)))
    await _settle(manager)
    assert [body["reason"] for body in channel.of("job_rejected")] == [
        "takeover_not_allowed_on_device", "profile_unavailable_on_device", "local_session_not_on_device",
        "folder_not_allowlisted_on_device"]

    await manager.handle("job_offer", offer(4))
    await _settle(manager)
    assert channel.of("turn_finished")[0]["status"] == "success"
    call = driver.calls[0]
    assert call["cwd"] == str(repo) and call["resume"] == SID and "CLAUDE_CONFIG_DIR" not in call["env"]
    assert call["fork"] is False
    assert notified == [("team", str(repo))]  # the Mac sees every remote turn

    # Phase B: a fork continues a copy of the same session in the same folder
    await manager.handle("job_offer", offer(5, fork_session=True))
    await _settle(manager)  # one after the other: two parallel turns finish in any order
    await manager.handle("job_offer", offer(6, fork_session="yes"))  # only a real true counts
    await _settle(manager)
    assert [call["fork"] for call in driver.calls[1:]] == [True, False]
    assert all(call["resume"] == SID for call in driver.calls)


def test_the_sdk_runs_a_take_over_with_the_profiles_own_settings(state, home, monkeypatch):
    from octryx_claude import launch

    local_profiles.connect(state, _profile(home, ".claude-private"), name="private")
    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    prepared = prepare_local(state, "private")
    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=SID, decide=None)
    assert captured["resume"] == SID and captured["permission_mode"] == "default"
    assert captured["fork_session"] is False
    SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=SID, decide=None, fork=True)
    assert captured["fork_session"] is True and captured["resume"] == SID  # a copy; the original stays untouched
    SdkDriver(sdk=fake_sdk)._options(prepared, cwd="/x", resume=None, decide=None, fork=True)
    assert captured["fork_session"] is False  # nothing to copy
    assert "mcp_servers" not in captured and "extra_args" not in captured
    assert captured["env"]["CLAUDE_CONFIG_DIR"].endswith(".claude-private")
    # Octryx's own state is never readable from a take-over
    deny = json.loads(captured["settings"])["permissions"]["deny"]
    assert deny == [f"Read(//{str(state.root).lstrip('/')}/**)", f"Edit(//{str(state.root).lstrip('/')}/**)"]


@pytest.mark.asyncio
async def test_every_tool_that_is_not_a_plain_read_asks_the_phone(state, home, monkeypatch):
    # Whatever the profile's allow rules say, a phone-started action is the person's decision
    from octryx_claude import launch

    local_profiles.connect(state, _profile(home, ".claude-private"), name="private")
    monkeypatch.setattr(launch, "resolve_claude", lambda: "/usr/local/bin/claude")
    captured = {}
    fake_sdk = types.SimpleNamespace(ClaudeAgentOptions=lambda **kwargs: captured.update(kwargs) or kwargs,
                                     HookMatcher=lambda **kwargs: kwargs)
    SdkDriver(sdk=fake_sdk)._options(prepare_local(state, "private"), cwd="/x", resume=SID, decide=None)
    hook = captured["hooks"]["PreToolUse"][0]["hooks"][0]
    asked = await hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "t1", None)
    assert asked["hookSpecificOutput"]["permissionDecision"] == "ask"
    for tool in ("Write", "Edit", "mcp__jira__create"):
        assert (await hook({"tool_name": tool}, "t", None))["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert await hook({"tool_name": "Read"}, "t2", None) == {"continue_": True}
    # Allow by default, block as an admin option: reading the web asks nobody.
    for tool in ("WebSearch", "WebFetch"):
        assert await hook({"tool_name": tool}, "t3", None) == {"continue_": True}
