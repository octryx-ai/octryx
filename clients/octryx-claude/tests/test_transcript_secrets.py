"""The Mac's pass over full transcripts uses the platform's own rules.

Two lines shape-only filters miss, an ``.env`` read with ``STRIPE_KEY=sk_live_…``
and the ``{"password": …}`` output of ``aws secretsmanager get-secret-value``, never leave the Mac. They are redacted
with their tool call in the same batch, in an earlier batch, and with no tool call at all. The command list stays
the live progress's, and a missing rules file sends nothing.
"""

from __future__ import annotations

import json

import httpx
import pytest

from octryx_claude import live_progress, transcript_redact, transcript_upload

from .test_transcript_upload import CONTEXT, SESSION, Platform, _files, _write

STRIPE = ("sk_live_" + "51HxQabcdefghijklmnopqrstu")
DB_PASSWORD = "app-db-pw-9f8e7d"
SECRET_PASSWORD = "hunter2-raw-value"
ENV_FILE = f"STRIPE_KEY={STRIPE}\nDATABASE_URL=postgres://app:{DB_PASSWORD}@db:5432/app\n"
SECRETS_OUTPUT = json.dumps({"Name": "prod/db", "SecretString": json.dumps({"password": SECRET_PASSWORD})})


def _read_call() -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": "/repo/.env"}}]}}


def _read_result() -> dict:
    return {"type": "user", "toolUseResult": {"file": {"filePath": "/repo/.env", "content": ENV_FILE}},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "content": ENV_FILE}]}}


def _secrets_call() -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {
        "command": "aws secretsmanager get-secret-value --secret-id prod/db"}}]}}


def _secrets_result() -> dict:
    return {"type": "user", "toolUseResult": {"stdout": SECRETS_OUTPUT},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "content": SECRETS_OUTPUT}]}}


def _sent(platform: Platform) -> str:
    return json.dumps(platform.batches)


@pytest.mark.parametrize("lines", [
    [_read_call(), _read_result(), _secrets_call(), _secrets_result()],
    [_read_result(), _secrets_result()],  # no tool call in sight: the content rules alone
], ids=["with-calls", "results-only"])
def test_the_two_incidents_never_leave_the_mac(state, tmp_path, lines):
    config = tmp_path / "config"
    main, _sub = _files(config)
    _write(main, lines)
    platform = Platform()
    with platform.client() as http:
        transcript_upload.Shipper(state, CONTEXT, config, SESSION).load().ship_round(http)
    for secret in (STRIPE, DB_PASSWORD, SECRET_PASSWORD):
        assert secret not in _sent(platform)


def test_a_secret_commands_output_in_a_later_batch_is_replaced_whole(state, tmp_path):
    config = tmp_path / "config"
    main, _sub = _files(config)
    _write(main, [_secrets_call()])
    platform = Platform()
    shipper = transcript_upload.Shipper(state, CONTEXT, config, SESSION).load()
    with platform.client() as http:
        shipper.ship_round(http)
        _write(main, [_secrets_result()])
        transcript_upload.Shipper(state, CONTEXT, config, SESSION).load().ship_round(http)  # after a restart
    later = platform.batches[-1]["lines"][0]
    assert later["toolUseResult"] == transcript_redact.SECRET_OUTPUT and "prod/db" not in json.dumps(later)


def test_the_command_list_is_the_live_progress_list():
    assert transcript_redact.rules().SECRET_COMMANDS.pattern == live_progress.SECRET_COMMANDS.pattern


def test_without_its_rules_file_nothing_is_sent(state, tmp_path, monkeypatch):
    def missing():
        raise ImportError("transcript_secrets")

    monkeypatch.setattr(transcript_redact, "rules", missing)
    config = tmp_path / "config"
    main, _sub = _files(config)
    _write(main, [_read_result()])
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500)))
    with client, pytest.raises(ImportError):
        transcript_upload.Shipper(state, CONTEXT, config, SESSION).load().ship_round(client)
    assert calls == []
