"""The ``seat`` profile (S0, root re-freeze 1b): the user's own subscription, a session-bound credential.

- ``--profile governed`` stays the default and keeps ``apiKeyHelper``;
- ``--profile seat`` is refused up front when the Workspace's client policy says so (nothing is
  registered, Claude Code never starts);
- otherwise the session is registered; the seat credential goes only into the child's
  ``ANTHROPIC_CUSTOM_HEADERS`` (and the session's private settings file), never into a log line;
- the seat child uses its own ``CLAUDE_CONFIG_DIR`` and has no ``apiKeyHelper``, so the subscription login
  owns ``Authorization``; nothing is written to ``~/.claude*`` (G1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octryx_claude import cli, launch, launch_settings, session_hooks
from octryx_claude.platform import PlatformResult

KEY = ("0b6c" + "4a52-3b1e-4c1b-9f55-1d1c1b1a1f10")
CREDENTIAL = "s3at-Cred_" + "x" * 40
ALIASES = {"main": "claude-sonnet-5", "opus": "claude-opus-5-5", "small_fast": "claude-sonnet-5"}


def _seat(launch_env, *, seat_mode="allowed", reason=None, credential=CREDENTIAL,
          header="X-Octryx-Seat-Credential"):
    launch_env["policy"] = PlatformResult(
        "ok", body={"state": "allowed", "seat": {"seat_mode": seat_mode, "reason": reason},
                    # The platform's picker (``launcher_picker``): one admitted company model.
                    "models": {"governed": [{"type": "model", "id": model, "display_name": model, "source": "company"}
                                            for model in ("claude-opus-5-5", "claude-sonnet-5")], "seat": [],
                               "seat_allows_governed_models": False}},
        status_code=200, state="allowed",
    )
    launch_env["register"] = PlatformResult(
        "ok", body={"state": "registered", "profile": "seat", "seat_credential": credential,
                    "credential_header": header},
        status_code=200, state="registered",
    )


def test_the_seat_model_env_carries_the_credential_header_and_no_helper_ttl():
    env = launch.model_env(base_url="https://octryx.example.test", session_key=KEY, workspace_id="ws-1",
                           work_item="BRD-6", aliases=ALIASES, seat_credential=CREDENTIAL)

    assert env["ANTHROPIC_BASE_URL"] == "https://octryx.example.test/api/v1/model-gateway/anthropic/seat"
    assert env["ANTHROPIC_CUSTOM_HEADERS"].splitlines()[-1] == f"X-Octryx-Seat-Credential: {CREDENTIAL}"
    assert "CLAUDE_CODE_API_KEY_HELPER_TTL_MS" not in env
    assert "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS" not in env


def test_only_the_governed_profile_sets_the_api_key_helper():
    common = {"shim": Path("/k/octryx-claude"), "state_root": Path("/s"), "env": {}, "policy": {},
              "base_url": "https://octryx.example.test"}

    assert "apiKeyHelper" in launch_settings.build_settings(**common)
    assert "apiKeyHelper" not in launch_settings.build_settings(**common, profile="seat")


def test_a_seat_session_registers_and_runs_with_its_own_login_dir(launch_env, monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _seat(launch_env)

    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 0

    assert launch_env["steps"][:4] == ["/client-policy", "/sessions/register", "/skills/manifest", "/sessions/hook-key"]
    assert launch_env["bodies"]["/sessions/register"]["profile"] == "seat"
    child = json.loads(launch_env["record"].read_text())["env"]
    state_root = launch_env["state"].root
    assert child["ANTHROPIC_BASE_URL"].endswith("/api/v1/model-gateway/anthropic/seat")
    assert f"X-Octryx-Seat-Credential: {CREDENTIAL}" in child["ANTHROPIC_CUSTOM_HEADERS"]
    assert child["CLAUDE_CONFIG_DIR"] == str(state_root / "claude-config-seat")
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"} & set(child)
    session_key = launch_env["code_intelligence"][0].session_key
    settings = json.loads((launch_env["state"].session_dir(session_key) / "settings.json").read_text())
    assert "apiKeyHelper" not in settings
    err = capsys.readouterr().err
    assert CREDENTIAL not in err and "profile seat" in err and "/login" in err
    assert not list(home.glob(".claude*")), "G1: nothing under ~/.claude*"


def test_a_workspace_that_forbids_seat_mode_refuses_before_registration(launch_env, capsys):
    _seat(launch_env, seat_mode="forbidden", reason="seat_classification_too_sensitive")

    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 2

    assert launch_env["steps"] == ["/client-policy"] and not launch_env["record"].exists()
    assert "denied: seat_classification_too_sensitive" in capsys.readouterr().err


def test_a_refused_registration_does_not_start_the_session(launch_env, capsys):
    _seat(launch_env)
    launch_env["register"] = PlatformResult("refused", status_code=403, state="denied", reason="seat_mode_forbidden")

    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 2

    assert not launch_env["record"].exists()
    assert "registration denied/seat_mode_forbidden" in capsys.readouterr().err


def test_an_unexpected_credential_or_header_name_is_never_used(launch_env, capsys):
    for credential, header in (("short", "X-Octryx-Seat-Credential"), (CREDENTIAL, "Authorization"),
                               ("bad value\nX-Injected: 1" + "x" * 40, "X-Octryx-Seat-Credential")):
        _seat(launch_env, credential=credential, header=header)
        assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 2
        assert not launch_env["record"].exists()
    assert "registration invalid_response" in capsys.readouterr().err


def test_the_governed_profile_registers_too_and_keeps_its_login_dir(launch_env):
    assert cli.main(["--", "-p", "hi"]) == 0

    assert launch_env["bodies"]["/sessions/register"]["profile"] == "governed"
    child = json.loads(launch_env["record"].read_text())["env"]
    assert child["CLAUDE_CONFIG_DIR"] == str(launch_env["state"].root / "claude-config")
    assert "Seat-Credential" not in child["ANTHROPIC_CUSTOM_HEADERS"]


def _session_end(state, monkeypatch, *, reason: str, transcript_root: Path) -> list[dict]:
    import io

    import httpx


    transcript = transcript_root / "projects" / "p" / "t.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(json.dumps({"type": "user", "cwd": "/w", "message": {"role": "user", "content": "hello"}}))
    hook_input = {"hook_event_name": "SessionEnd", "transcript_path": str(transcript), "cwd": "/w",
                  "session_id": KEY, "reason": reason}
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps(hook_input).encode())))
    monkeypatch.setenv("OCTRYX_BASE_URL", "https://octryx.example.test")
    monkeypatch.setenv("OCTRYX_SESSION_KEY", KEY)
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", "ws-1")
    bodies: list[dict] = []

    def handler(request):
        if request.url.path.endswith("/sessions/finalize"):  # the lessons call (session_lessons) is its own test
            bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"state": "finalized"})

    assert session_hooks.run_session_end(state, httpx.Client(transport=httpx.MockTransport(handler))) == 0
    return bodies


@pytest.mark.parametrize("profile", ["governed", "seat"])
def test_a_real_session_end_finalizes_with_the_profiles_transcript(state, monkeypatch, profile):
    """C1: the seat profile's transcript lives in ``claude-config-seat/`` and still yields the digest."""
    [body] = _session_end(state, monkeypatch, reason="prompt_input_exit",
                          transcript_root=state.claude_config_dir_for(profile))

    assert "hello" in body["transcript_digest"] and body["end_reason"] == "prompt_input_exit"


@pytest.mark.parametrize("profile", ["governed", "seat"])
def test_clear_never_finalizes_so_the_session_stays_alive(state, monkeypatch, profile):
    """C2: /clear ends a conversation, not the session: no finalize, so no stop and no revocation."""
    assert _session_end(state, monkeypatch, reason="clear", transcript_root=state.claude_config_dir_for(profile)) == []


def test_a_transcript_outside_the_octryx_config_dirs_is_never_read(state, monkeypatch, tmp_path):
    [body] = _session_end(state, monkeypatch, reason="logout", transcript_root=tmp_path / "elsewhere")

    assert body["transcript_digest"] == ""


def test_a_second_instance_reuses_the_first_instances_seat_login_dir(tmp_path, monkeypatch):
    """Local dev loop: Claude Code keys the seat login by the exact config dir string, so a second
    launcher instance with its own OCTRYX_CLAUDE_HOME names the first one's seat dir verbatim instead of a new login."""
    from octryx_claude.state import LocalState

    first = tmp_path / "team" / "claude-config-seat"
    first.mkdir(parents=True)
    second = LocalState(tmp_path / "local")
    assert second.claude_config_dir_for("seat") == second.root / "claude-config-seat"

    monkeypatch.setenv("OCTRYX_CLAUDE_SEAT_CONFIG_DIR", str(first))

    assert second.claude_config_dir_for("seat") == first
    assert second.claude_config_dir_for("governed") == second.root / "claude-config"
