"""One list of known secret forms: the platform's redaction and the transcript rules (which
the launcher runs from its vendored copy) both read ``backend/scripts/secret_patterns.py``; neither keeps a copy."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.services.redaction_policy import REDACTED_SECRET, redact_secret_text

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PATTERNS = _load("secret_patterns")
TRANSCRIPT = _load("transcript_secrets")
# One made-up value per form (shapes only; none of them is or was a real credential).
SAMPLES = {
    "github-pat": "ghp_" + "a1B2" * 9,
    "github-fine-grained-pat": "github_pat_" + "A" * 82,
    "github-oauth": "gho_" + "a1B2" * 9,
    "github-app-token": "ghs_" + "a1B2" * 9,
    "github-refresh-token": "ghr_" + "a1B2" * 9,
    "github-token-loose": "ghp_" + "a1B2" * 6,
    "gitlab-pat": "glpat-" + "x" * 20,
    "slack-bot-token": "xoxb-" + "1" * 10 + "-" + "2" * 13 + "-abc",
    "slack-user-token": "xoxp-" + "-".join(["1" * 10] * 3) + "-" + "a" * 30,
    "slack-token-loose": "xoxa-" + "1" * 12,
    "aws-access-token": "AKIA" + "ABCDEFGHIJKLMNOP",
    "aws-access-token-loose": "ASIA" + "ABCDEFGH12345678",
    "anthropic-api-key": "sk-ant-api03-" + "x" * 80,
    "openai-api-key": "sk-proj-" + "x" * 40,
    "stripe-access-token": "sk_" + "live_" + "a1b2c3d4e5",
    "stripe-restricted-loose": "rk_" + "a1b2c3d4" * 2,
    "gcp-api-key": "AIza" + "x" * 35,
    "jwt": "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12,
    "telegram-bot-api-token": "100000001:A" + "Synthetic_Telegram-" + "x" * 15,
}


def test_every_form_has_a_sample():
    assert {form for form, _pattern in PATTERNS.KNOWN_TOKENS} == set(SAMPLES)


@pytest.mark.parametrize(("form", "value"), list(SAMPLES.items()))
def test_the_platform_and_the_transcript_rules_hide_every_known_form(form, value):
    text = f"printed {value} here"
    assert value not in redact_secret_text(text) and REDACTED_SECRET in redact_secret_text(text), form
    assert value not in TRANSCRIPT.redact_text(text), form


@pytest.mark.parametrize(("form", "value"), list(SAMPLES.items()))
def test_the_session_summary_hides_every_known_form_too(form, value):
    summary = _load("mcp_session_ingest_common")
    assert value not in summary.redact(f"printed {value} here"), form


def test_no_second_copy_of_the_list():
    for source in (SCRIPTS / "transcript_secrets.py",
                   Path(__file__).resolve().parents[3] / "app/services/redaction_policy.py"):
        text = source.read_text(encoding="utf-8")
        # A token regex of its own (the prefix tuple of redaction_policy, which marks whole values, is no pattern).
        assert not any(shape in text for shape in ("AKIA", "glpat-[", "xox[", "{36}", "eyJ[")), source.name
    assert not (Path(__file__).resolve().parents[3] / "app/services/secret_patterns.json").exists()
