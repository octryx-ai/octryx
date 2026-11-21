"""Secrets are redacted with a prefixed name, in JSON and YAML, quoted, in URLs and in their known forms without any
name (e.g. GITHUB_TOKEN=… and DB_PASSWORD=… never pass unchanged)."""

from __future__ import annotations

import pytest

from app.services.redaction_policy import REDACTED_SECRET, looks_like_secret_value, redact_secret_text

GHP = "ghp_" + "a1B2" * 9
LEAKS = {
    ("GITHUB_TOKEN=ghx_" + "abc123secret"): ("ghx_" + "abc123secret"),
    "export DB_PASSWORD=hunter2hunter2": "hunter2hunter2",
    ("AWS_SECRET_ACCESS_KEY: wJal" + "rXUtnFEMI/K7MDENG"): ("wJal" + "rXUtnFEMI/K7MDENG"),
    'db.password = "correct horse battery"': "correct horse battery",
    '{"password": "s3cr3t value", "user": "ana"}': "s3cr3t value",
    "client_secret: 'abc def 123'": "abc def 123",
    "password: hunter2hunter2": "hunter2hunter2",
    f"cloned with {GHP} today": GHP,
    "github_pat_" + "A" * 82: "github_pat_" + "A" * 82,
    "key AKIAIOSFODNN7EXAMPLE in env": "AKIAIOSFODNN7EXAMPLE",
    "OPENAI sk-proj-" + "x" * 40: "sk-proj-" + "x" * 40,
    ("slack xoxb-12" + "34567890-1234567890123-abcdefABCDEF"): ("xoxb-12" + "34567890-1234567890123-abcdefABCDEF"),
    "Authorization: Bearer abcdefghijklmnop": "abcdefghijklmnop",
    "https://ana:pw-1234@example.com/repo.git": "pw-1234",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----": "MIIEow",
}


@pytest.mark.parametrize(("text", "secret"), list(LEAKS.items()))
def test_every_secret_form_is_redacted(text, secret):
    redacted = redact_secret_text(text)
    assert secret not in redacted and REDACTED_SECRET in redacted
    assert looks_like_secret_value(text)


def test_the_name_stays_readable_and_what_is_no_secret_stays():
    assert redact_secret_text("GITHUB_TOKEN=abc123secret") == "GITHUB_TOKEN=[redacted]"
    assert redact_secret_text('{"password": "x y"}') == '{"password": [redacted]}'
    for text in ("tokenizer=wordpiece", "see password_policy_doc for the rules", "max_tokens: 4096",
                 "tokens: 12", "the token expired"):
        assert redact_secret_text(text) == text, text


def test_an_unquoted_value_runs_to_whitespace_and_a_quoted_one_honours_escapes():
    assert redact_secret_text("password=ab,cd next") == "password=[redacted] next"
    assert redact_secret_text('{"password": "a\\"b rest", "user": "ana"}') == '{"password": [redacted], "user": "ana"}'


def test_a_kebab_name_starting_with_sk_is_redacted_on_purpose():
    # Over-redaction by choice: an OpenAI key and ``sk-`` plus 20 name characters have the same shape, and a
    # hidden identifier costs less than a leaked key.
    assert redact_secret_text("use sk-learn-compatible-estimators here") == f"use {REDACTED_SECRET} here"
