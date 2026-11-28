from __future__ import annotations

import json

import pytest

from octryx_claude import cli, model_picker, status_block
from octryx_claude.platform import PlatformResult

from .test_seat_profile import CREDENTIAL

COMPANY = {"type": "model", "id": "octryx-general", "display_name": "General model",
           "description": "Company model through Octryx, billed to the Workspace budget", "source": "company"}
SUBSCRIPTION = {"type": "model", "id": "claude-sonnet-5", "display_name": "claude-sonnet-5",
                "description": "Your own Claude subscription", "source": "subscription"}
SEAT_COMPANY = {**COMPANY, "id": "company/octryx-general", "display_name": "General model (company)"}


def _policy(*, seat_mode: str = "allowed", opt_in: bool = True) -> dict:
    return {"state": "allowed", "seat": {"seat_mode": seat_mode, "reason": None},
            "models": {"governed": [COMPANY], "seat": [SUBSCRIPTION, SEAT_COMPANY] if opt_in else [SUBSCRIPTION],
                       "seat_allows_governed_models": opt_in}}


def _session_settings(launch_env) -> dict:
    session_key = launch_env["code_intelligence"][0].session_key
    return json.loads((launch_env["state"].session_dir(session_key) / "settings.json").read_text())


def test_rows_are_validated_and_malformed_ones_dropped():
    policy = {"models": {"governed": [
        COMPANY,
        COMPANY,  # duplicate
        {**COMPANY, "id": "bad id with spaces"},
        {**COMPANY, "id": "octryx-x", "source": "elsewhere"},
        {**COMPANY, "id": "octryx-y", "display_name": "line\nbreak", "description": "d" * 201},
        "not a row",
    ]}}

    rows = model_picker.picker_rows(policy, "governed")

    assert rows == [
        {"model": "octryx-general", "label": "General model", "description": COMPANY["description"],
         "source": "company"},
        {"model": "octryx-y", "label": "octryx-y", "description": "", "source": "company"},
    ]
    assert model_picker.model_picker_setting(rows) == {"options": [
        {"model": "octryx-general", "label": "General model", "description": COMPANY["description"]},
        {"model": "octryx-y", "label": "octryx-y"},
    ]}
    assert model_picker.picker_rows({}, "governed") == [] and model_picker.model_picker_setting([]) is None
    assert model_picker.picker_rows({"models": {"seat": "x"}}, "seat") == []
    assert len(model_picker.picker_rows({"models": {"governed": [
        {**COMPANY, "id": f"ocx-{index}"} for index in range(60)]}}, "governed")) == model_picker.MAX_ROWS


def test_the_governed_session_gets_the_picker_and_gateway_discovery(launch_env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "0")  # the parent's value never wins
    launch_env["policy"] = PlatformResult("ok", body=_policy(), status_code=200, state="allowed")

    assert cli.main(["--profile", "governed", "--", "-p", "hi"]) == 0

    child = json.loads(launch_env["record"].read_text())["env"]
    settings = _session_settings(launch_env)
    assert child["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
    assert settings["env"]["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "1"
    assert settings["modelPicker"] == {"options": [
        {"model": "octryx-general", "label": "General model", "description": COMPANY["description"]}]}
    assert "replaceBuiltInOptions" not in settings["modelPicker"]
    assert not list(home.glob(".claude*")), "G1: nothing under ~/.claude*"


def test_the_seat_session_gets_its_own_picker_and_no_discovery(launch_env, capsys):
    launch_env["policy"] = PlatformResult("ok", body=_policy(), status_code=200, state="allowed")
    launch_env["register"] = PlatformResult(
        "ok", body={"state": "registered", "profile": "seat", "seat_credential": CREDENTIAL,
                    "credential_header": "X-Octryx-Seat-Credential"}, status_code=200, state="registered")

    assert cli.main(["--profile", "seat", "--", "-p", "hi"]) == 0

    child = json.loads(launch_env["record"].read_text())["env"]
    settings = _session_settings(launch_env)
    assert child["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] == "0"
    assert [option["model"] for option in settings["modelPicker"]["options"]] == [
        "claude-sonnet-5", "company/octryx-general"]
    assert settings["modelPicker"]["options"][1]["label"] == "General model (company)"
    err = capsys.readouterr().err
    assert ("company models (/model):         company/octryx-general (billed to the Workspace budget)") in err


def test_a_platform_without_a_picker_writes_none(launch_env):
    assert cli.main(["--profile", "governed", "--", "-p", "hi"]) == 0

    assert "modelPicker" not in _session_settings(launch_env)


@pytest.mark.parametrize(("policy", "profile", "label"), [
    (_policy(), "governed", "octryx-general"),
    (_policy(), "seat", "company/octryx-general (billed to the Workspace budget)"),
    (_policy(opt_in=False), "seat", "not offered in seat sessions (subscription models only)"),
    ({"models": {"governed": [], "seat": [], "seat_allows_governed_models": True}}, "seat",
     "none admitted for this Workspace"),
    ({"models": {"governed": []}}, "governed", "none admitted for this Workspace"),
    ({"models": {"governed": [{**COMPANY, "id": f"ocx-{index}"} for index in range(6)]}}, "governed",
     "ocx-0, ocx-1, ocx-2, ocx-3 +2 more"),
    ({"state": "allowed"}, "governed", "none admitted for this Workspace"),
])
def test_the_status_label(policy, profile, label):
    assert model_picker.status_label(policy, profile) == label


def test_the_status_block_shows_the_company_models_of_the_chosen_profile(state):
    result = PlatformResult("ok", body=_policy(seat_mode="forbidden", opt_in=False), status_code=200,
                            state="allowed")

    lines = status_block.lines_for(state, result, "ok", workspace="Example (ws-1)", requested="governed",
                                   model="octryx-general")

    assert "octryx-claude:   company models (/model):         octryx-general" in lines
    refused = PlatformResult("refused", status_code=409, state="needs_configuration", reason="policy_missing")
    assert not [line for line in status_block.lines_for(state, refused, "x", workspace="w", requested="governed")
                if "company models" in line]


def test_status_says_needs_configuration_when_neither_a_company_model_nor_the_seat_can_run_a_session(state):
    def governed_line(body):
        result = PlatformResult("ok", body=body, status_code=200, state="allowed")
        lines = status_block.lines_for(state, result, "ok", workspace="w", requested="auto")
        return next(line for line in lines if "governed (company model):" in line)

    nothing = {**_policy(seat_mode="forbidden", opt_in=False), "models": {"governed": [], "seat": [],
                                                                          "seat_allows_governed_models": False}}
    line = governed_line(nothing)
    assert "needs_configuration: no Claude model admitted and seat not allowed" in line
    assert "Anthropic key or Bedrock with Claude" in line and "allows Claude Code seats" in line
    # Ready: a company model admitted.
    assert governed_line(_policy(seat_mode="forbidden", opt_in=False)).endswith(" ready")
    # The seat allowed but no company model: governed is not "ready" (outsider walk read as a
    # contradiction next to "company models: none admitted"), and with no seat login nothing can run a session.
    seat_allowed = {**nothing, "seat": {"seat_mode": "allowed", "reason": None}}
    assert governed_line(seat_allowed).endswith(status_block.GOVERNED_NO_COMPANY_MODEL)
    result = PlatformResult("ok", body=seat_allowed, status_code=200, state="allowed")
    lines = status_block.lines_for(state, result, "ok", workspace="w", requested="auto")
    assert lines[-1] == f"octryx-claude:   {status_block.NO_MODEL_AVAILABLE}"
    assert "octryx-claude login --seat" in lines[-1]
    (state.root / ".seat-session-ok").touch()  # a seat that works: a session can run, no "no model available"
    lines = status_block.lines_for(state, result, "ok", workspace="w", requested="auto")
    assert status_block.NO_MODEL_AVAILABLE not in "".join(lines)


def test_the_status_says_when_the_governed_main_model_is_not_admitted_here():
    from octryx_claude import status_block
    from octryx_claude.launch_process import PROFILE_GOVERNED, PROFILE_SEAT

    policy = {"models": {PROFILE_GOVERNED: [{"id": "assistant-large", "source": "company"}]}}
    note = status_block.admitted_note(policy, PROFILE_GOVERNED, "claude-opus-5-5")
    assert note.startswith("claude-opus-5-5 — not admitted here") and "/model" in note
    assert status_block.admitted_note(policy, PROFILE_GOVERNED, "assistant-large") == "assistant-large"
    assert status_block.admitted_note(policy, PROFILE_SEAT, "claude-opus-5-5") == "claude-opus-5-5"
    assert status_block.admitted_note({}, PROFILE_GOVERNED, "claude-opus-5-5") == "claude-opus-5-5", "no list: no claim"
