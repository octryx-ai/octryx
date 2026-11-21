"""A device's job messages carry no secret values in their output fields: a pipeline step
that printed ``DB_PASSWORD=…`` or a token left the device unredacted; now the outbox never even writes it."""

from __future__ import annotations

import pytest

from octryx_claude import output_redact
from octryx_claude.device_channel import ChannelClient
from octryx_claude.device_outbox import Outbox

TOKEN = "ghp_" + "a1B2" * 9  # made-up shape


def _body() -> dict:
    return {"job_id": "dj_1", "commit": "0" * 40, "path": "src/app.py",
            "result": {"steps": [{"command": "pytest", "exit_code": 1,
                                  "output_tail": f"E  DB_PASSWORD=hunter2hunter2\nclone with {TOKEN}"}],
                       "hands_on": {"error": "login failed: Authorization: Bearer abcdefghijklmnop"}}}


@pytest.mark.asyncio
async def test_the_outbox_never_holds_a_secret_and_the_rest_stays_exact(state):
    client = ChannelClient(state, token_provider=lambda force: "t", report=lambda: {})
    client.outbox = Outbox(state)
    await client.send_job("dj_1", "job_finished", _body())

    stored = client.outbox.pending("dj_1")[0]["body"]
    tail = stored["result"]["steps"][0]["output_tail"]
    assert "hunter2hunter2" not in tail and TOKEN not in tail and "DB_PASSWORD=" in tail
    assert "abcdefghijklmnop" not in stored["result"]["hands_on"]["error"]
    assert (stored["commit"], stored["path"], stored["result"]["steps"][0]["command"]) == ("0" * 40, "src/app.py",
                                                                                          "pytest")


def test_without_the_rules_an_output_field_goes_out_as_a_placeholder(monkeypatch):
    def missing():
        raise ImportError("transcript_secrets")

    monkeypatch.setattr("octryx_claude.transcript_redact.rules", missing)
    body = output_redact.redact_outputs(_body())
    assert body["result"]["steps"][0]["output_tail"] == output_redact.UNAVAILABLE
    assert body["commit"] == "0" * 40
