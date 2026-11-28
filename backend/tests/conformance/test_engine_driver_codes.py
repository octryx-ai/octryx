from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflow_runs.octryx.turn_failures import failed_turn_explanation
from app.services.workflow_runs.pause_causes import cause_of, split_reason

# Each engine's driver code for the same event (clients/octryx-claude: device_session, device_sdk, codex_driver) and
# whether the device rejects the turn before any agent ran (job_rejected) or the turn ends failed (turn_finished).
DRIVER_CODES = [
    ("missing binary", "claude_not_installed", "codex_not_installed", True),
    ("driver unavailable", "claude_agent_sdk_missing", "codex_too_old", True),
    ("start failed", "claude_start_failed", "codex_session_incomplete", False),
    ("start timed out", "claude_initialize_timeout", "codex_turn_failed", False),
    ("interrupted", "interrupted", "codex_turn_interrupted", False),
]
SCENARIOS = Path(__file__).with_name("scenarios.json")


def _platform_state(code: str, *, rejected: bool) -> tuple[str, str, str]:
    stored, _message = failed_turn_explanation(code, "", rejected=rejected)
    reason = split_reason("runtime_failed", {"code": stored})
    cause, _rule = cause_of(reason, {"code": stored})
    return stored, reason, cause


@pytest.mark.parametrize(("event", "claude", "codex", "rejected"), DRIVER_CODES, ids=[row[0] for row in DRIVER_CODES])
def test_both_engines_driver_codes_reach_the_same_platform_state(event, claude, codex, rejected):
    _claude_code, claude_reason, claude_cause = _platform_state(claude, rejected=rejected)
    _codex_code, codex_reason, codex_cause = _platform_state(codex, rejected=rejected)
    assert (claude_reason, claude_cause) == (codex_reason, codex_cause) == ("turn_failed", "environment"), event


def test_an_unknown_model_is_named_on_codex_only_and_that_difference_is_recorded():
    accepted = json.loads(SCENARIOS.read_text(encoding="utf-8"))["accepted_differences"]
    assert "unknown_model_state" in accepted
    assert _platform_state("codex_error_modelNotFound", rejected=False)[1:] == ("turn_failed", "environment")
