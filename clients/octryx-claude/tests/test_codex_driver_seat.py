from __future__ import annotations

import asyncio
import tomllib

from octryx_claude import codex_config, codex_driver
from tests.codex_appserver_fake import fake_appserver
from tests.codex_driver_support import _prepared, _stop_replay


def test_a_seat_session_uses_the_persons_login_through_the_platforms_seat_route(tmp_path):
    from octryx_claude import codex_seat

    state = tmp_path / "state"
    seat_home = codex_seat.ensure_seat_home(state)
    (seat_home / "auth.json").write_text("{\"tokens\": \"person's own login\"}")
    prepared = _prepared(tmp_path, OCTRYX_CLAUDE_HOME=str(state))
    prepared.extra.update(codex_seat=True, seat_credential="seat-cred-123", state_root=str(state))
    prepared.model = ""
    home = codex_driver.prepare_home(prepared, sandboxed=False)
    config = tomllib.loads((home / "config.toml").read_text())
    provider = config["model_providers"]["octryx_seat"]
    assert config["model_provider"] == "octryx_seat" and "model" not in config  # Codex's own default model
    assert provider["base_url"] == "https://platform.test/api/v1/model-gateway/openai/seat"
    assert provider["requires_openai_auth"] is True and "auth" not in provider
    assert provider["env_http_headers"] == {"X-Octryx-Seat-Credential": codex_seat.SEAT_CREDENTIAL_ENV}
    assert config["cli_auth_credentials_store"] == "file"
    link = home / "auth.json"
    assert link.is_symlink() and link.resolve() == (seat_home / "auth.json").resolve()
    files = (home / "config.toml").read_text() + (home / codex_config.ENV_WRAPPER).read_text()
    assert "seat-cred-123" not in files and "person's own login" not in files
    assert codex_driver.environment(prepared, home)[codex_seat.SEAT_CREDENTIAL_ENV] == "seat-cred-123"


def test_the_seat_login_and_status_use_codex_own_login_in_the_seat_home(tmp_path):
    from octryx_claude import codex_seat

    log = tmp_path / "calls.txt"
    codex = tmp_path / "codex"
    codex.write_text("#!/bin/sh\necho \"$CODEX_HOME $*\" >> " + str(log) + "\n"
                     "[ \"$1 $2\" = \"login status\" ] && exit 1\nexit 0\n")
    codex.chmod(0o755)
    assert codex_seat.logged_in(str(codex), tmp_path / "state") is False
    assert codex_seat.login(str(codex), tmp_path / "state", device_auth=True) == 0
    calls = log.read_text().splitlines()
    assert calls[0].endswith("codex-seat login status") and calls[1].endswith("codex-seat login --device-auth")
    assert (tmp_path / "state" / "codex-seat" / "config.toml").read_text().startswith(
        'cli_auth_credentials_store = "file"')


def test_the_device_reports_the_codex_seat_login_from_the_exit_code_only_and_cached(tmp_path):
    # The platform learns logged in yes/no (``codex_seat_login``); no login file means no Codex run at all,
    # and the answer is reused until it is old or the login file changes.
    from octryx_claude import codex_seat

    codex_seat._reported.clear()
    state = tmp_path / "state"
    calls = tmp_path / "calls.txt"
    codex = tmp_path / "codex"
    codex.write_text("#!/bin/sh\necho \"$*\" >> " + str(calls) + "\necho 'Logged in using ChatGPT'\nexit 0\n")
    codex.chmod(0o755)
    now = [100.0]

    def ask() -> bool:
        return codex_seat.reported_login(state, codex=lambda: str(codex), clock=lambda: now[0])

    assert ask() is False and not calls.exists(), "no login file: Codex is not asked"
    auth = codex_seat.ensure_seat_home(state) / "auth.json"
    auth.write_text("{}")
    assert ask() is True and ask() is True
    assert calls.read_text().splitlines() == ["login status"], "cached"
    now[0] += codex_seat.REPORT_CACHE_SECONDS
    codex.write_text("#!/bin/sh\necho \"$*\" >> " + str(calls) + "\nexit 1\n")
    assert ask() is False and len(calls.read_text().splitlines()) == 2
    assert codex_seat.reported_login(state, codex=lambda: "", clock=lambda: now[0] + 10_000) is False
    codex_seat._reported.clear()


def test_a_codex_seat_at_its_usage_limit_reports_the_fixed_code_not_the_text(tmp_path, monkeypatch):
    from octryx_claude import plain_driver

    monkeypatch.setattr(plain_driver, "judged_stop", _stop_replay((None, True)))
    limited = fake_appserver(tmp_path / "bin", turns=[[
        {"notify": "item/completed", "params": {"item": {"id": "a", "type": "agentMessage",
                                                         "text": "I hit a rate limit earlier."}}},
        {"status": "failed", "error": {"message": "You've hit your usage limit. Try again in 2 hours."}}]])

    async def emit(_event):
        return None

    result = asyncio.run(codex_driver.CodexDriver(str(limited)).run_turn(
        _prepared(tmp_path), cwd=str(tmp_path), prompt="x", resume=None, emit=emit))
    assert (result["status"], result["error"]) == ("error", "usage_limit")


def test_no_turn_searches_at_the_provider_not_even_a_research_phase_on_the_seat(tmp_path):
    def config(sub: str, **extra) -> dict:
        prepared = _prepared(tmp_path / sub)
        prepared.extra.update(extra)
        home = codex_driver.prepare_home(prepared, sandboxed=False)
        return tomllib.loads((home / "config.toml").read_text())

    seat = {"codex_seat": True, "state_root": str(tmp_path / "state")}
    (tmp_path / "state").mkdir()
    assert config("governed", web=True)["web_search"] == "disabled"  # company models refuse the tool type
    research = config("seat-web", web=True, **seat)
    assert research["web_search"] == "disabled"  # web access only through the platform's web tools
    assert "supports_standalone_web_search" not in research["model_providers"]["octryx_seat"]
    assert config("seat-other", **seat)["web_search"] == "disabled"


def test_the_seats_windows_are_read_from_the_threads_rollout(tmp_path):
    import json as _json

    day = tmp_path / "2026" / "11" / "16"
    day.mkdir(parents=True)
    windows = {"primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": 1794850112},
               "secondary": {"used_percent": 25.0, "window_minutes": 10080, "resets_at": 1795343694}}
    rows = [{"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "codex", **{key: {**value, "used_percent": 50.0} for key, value in windows.items()}}}},
            {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {"limit_id": "codex", **windows}}},
            {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
                "limit_id": "premium", "primary": None, "secondary": None}}}]
    (day / "rollout-2026-11-16T15-34-55-thread-1.jsonl").write_text("\n".join(_json.dumps(row) for row in rows))

    assert codex_driver.rollout_rate_limits(tmp_path, "thread-1") == windows
    assert codex_driver.rollout_rate_limits(tmp_path, "thread-2") is None
    assert codex_driver.rollout_rate_limits(tmp_path, "../x") is None
