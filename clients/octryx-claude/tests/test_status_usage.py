"""The status block shows the Workspace as ``name (id)``, the user's seat allowance and daily budget."""

from __future__ import annotations

import time

import pytest

from octryx_claude import cli, cli_account, cli_launch, cli_session, status_block, supervisor, usage, workspaces
from octryx_claude.platform import PlatformResult
from octryx_claude.seat_status import SeatState

from .test_seat_profile import _seat

NOW = 1_790_000_000.0


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _clock(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def _ok(body: dict) -> PlatformResult:
    return PlatformResult("ok", body=body, status_code=200, state=str(body.get("state") or ""),
                          reason=str(body.get("reason") or ""))


def test_the_budget_label_for_every_state():
    resets = NOW + 3600
    allowed = _ok({"state": "allowed", "limit_usd": 50, "spent_usd": 3.25, "resets_at": _iso(resets)})
    assert usage.budget_label(allowed) == f"3.25 / 50.00 USD today (resets {_clock(resets)})"
    denied = _ok({"state": "denied", "reason": "gateway_daily_budget_exhausted", "limit_usd": 3, "spent_usd": 3.5})
    assert usage.budget_label(denied) == "3.50 / 3.00 USD today, used up (gateway_daily_budget_exhausted)"
    missing = _ok({"state": "needs_configuration", "reason": "gateway_policy_invalid", "limit_usd": None})
    assert usage.budget_label(missing) == "not configured (gateway_policy_invalid)"
    assert usage.budget_label(PlatformResult("refused", status_code=404)) == "unavailable (404)"
    assert usage.budget_label(PlatformResult("refused", status_code=403, state="denied",
                                             reason="workspace_not_authorized")) == (
        "unavailable (denied/workspace_not_authorized)")
    assert usage.budget_label(PlatformResult("unreachable", reason="platform_unreachable")) == (
        "unavailable (platform_unreachable)")
    for bad in ({"limit_usd": "50", "spent_usd": 1}, {"limit_usd": float("nan"), "spent_usd": 1},
                {"limit_usd": 50, "spent_usd": -1}, {"limit_usd": True, "spent_usd": 1}):
        assert usage.budget_label(_ok({"state": "allowed", **bad})) == "unavailable (invalid_response)", bad


def test_the_allowance_label():
    future, past = NOW + 7200, NOW - 60
    body = {"five_hour_pct": 42.4, "five_hour_resets_at": _iso(future), "seven_day_pct": 13,
            "seven_day_resets_at": _iso(future), "status": "allowed", "updated_at": _iso(NOW - 120)}
    label = usage.allowance_label(_ok({"seat_allowance": body}), now=NOW)
    assert label == f"5h 42% · 7d 13% (as of {_clock(NOW - 120)})"
    stale = {**body, "five_hour_resets_at": _iso(past), "status": "rejected", "updated_at": None}
    stale_label = usage.allowance_label(_ok({"seat_allowance": stale}), now=NOW)
    assert stale_label == "5h reset since · 7d 13%, limit reached"
    odd = {"five_hour_pct": "42", "seven_day_pct": float("inf")}
    assert usage.allowance_label(_ok({"seat_allowance": odd}), now=NOW) == "5h n/a · 7d n/a"
    assert usage.allowance_label(_ok({"seat_allowance": None}), now=NOW) == "not reported yet (shown after a seat turn)"
    assert usage.allowance_label(PlatformResult("refused", status_code=404)) == "unavailable (404)"


@pytest.mark.parametrize(("code", "shown"), [("ready", True), ("not_logged_in", True), ("forbidden", False),
                                             ("unknown", False)])
def test_the_allowance_line_only_where_seat_can_be_used(code, shown):
    result = _ok({"state": "allowed", "limit_usd": 50, "spent_usd": 0, "seat_allowance": None})
    lines = status_block.render(workspace_label="Acme Orders (ws-1)", seat=SeatState(code, code), governed="ready",
                                usage_result=result)
    assert any("seat allowance:" in line for line in lines) is shown
    assert any("daily budget:                    0.00 / 50.00 USD today" in line for line in lines)


def test_no_usage_line_when_governance_is_not_set_up(state):
    refused = PlatformResult("refused", status_code=409, state="needs_configuration", reason="policy_missing")
    lines = status_block.lines_for(state, refused, "needs_configuration/policy_missing", workspace="ws-1",
                                   requested="auto", usage_result=_ok({"state": "allowed"}))
    assert not any("allowance" in line or "budget" in line for line in lines)


def test_a_stored_id_without_a_name_is_shown_as_name_and_id(launch_env, monkeypatch, capsys):
    _seat(launch_env)
    launch_env["workspaces"] = [workspaces.Workspace("ws-0", "Other"), workspaces.Workspace("ws-1", "Acme Orders")]
    launch_env["usage"] = _ok({"state": "needs_configuration", "reason": "gateway_policy_invalid"})
    monkeypatch.setattr(supervisor, "supervise", lambda argv, env: 0)

    assert cli.main(["--", "-p", "hi"]) == 0

    err = capsys.readouterr().err
    assert "octryx-claude: Workspace Acme Orders (ws-1)\n" in err
    assert "daily budget:                    not configured (gateway_policy_invalid)" in err
    assert launch_env["usage_reads"] == ["/daily-budget?workspace_id=ws-1"]


def test_an_unknown_name_keeps_the_id(state, monkeypatch):
    monkeypatch.setattr(workspaces, "fetch_workspaces", lambda *_a, **_k: None)
    assert workspaces.resolved_label(state, None, "https://octryx.example.test", {}, "ws-1") == "ws-1"
    monkeypatch.setattr(workspaces, "fetch_workspaces", lambda *_a, **_k: [workspaces.Workspace("ws-1", "")])
    assert workspaces.resolved_label(state, None, "https://octryx.example.test", {}, "ws-1") == "ws-1"
    config = {"workspace_id": "ws-1", "workspace_name": "Acme Orders"}
    assert workspaces.resolved_label(state, None, "https://octryx.example.test", config, "ws-1") == "Acme Orders (ws-1)"


def test_status_resolves_the_name_and_shows_the_usage(state, monkeypatch, capsys):
    state.write_config({"base_url": "https://octryx.example.test", "workspace_id": "ws-1"})
    monkeypatch.setattr(workspaces, "fetch_workspaces",
                        lambda *_a, **_k: [workspaces.Workspace("ws-1", "Acme Orders")])

    def control_plane(state_arg, context, method, path, *, http, timeout, body=None):
        if path.startswith("/daily-budget"):
            return _ok({"state": "allowed", "limit_usd": 50, "spent_usd": 12.5, "seat_allowance": None})
        return _ok({"state": "allowed", "seat": {"seat_mode": "allowed"}})

    for module in (cli_launch, cli_session, cli_account):
        monkeypatch.setattr(module, "call_control_plane", control_plane)
    monkeypatch.setattr(usage, "call_control_plane", control_plane)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "workspace:  Acme Orders (ws-1)\n" in out and "octryx-claude: Workspace Acme Orders (ws-1)\n" in out
    assert "seat allowance:                  not reported yet (shown after a seat turn)" in out
    assert "daily budget:                    12.50 / 50.00 USD today" in out
