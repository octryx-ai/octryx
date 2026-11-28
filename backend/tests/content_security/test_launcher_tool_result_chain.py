"""One chain from a built-in tool's output to the next provider-bound request (``launcher_chain_support``)."""

from __future__ import annotations

import json

import pytest

from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from tests.content_security.launcher_chain_support import (
    MESSAGES,
    hook_input,
    launcher,
    next_request,
    platform_session,
    run_hook,
)
from tests.model_gateway.inbound_gateway_support import gateway_setup  # noqa: F401 - fixture

# Credential assignments (a gateway kind) past a detector's candidate limit: no scan finishes.
FRAGMENT = "password=Value0x"
DENSE = " ".join(f"password=Value{index}x" for index in range(5200))


@pytest.mark.asyncio
async def test_a_withheld_builtin_output_never_reaches_the_provider(client, db, tmp_path, monkeypatch,
                                                                   gateway_setup):  # noqa: F811
    from tests.model_gateway.conftest import ALIAS

    set_policy_runtime(PolicyRuntime())
    _hook, content_hooks, *_rest = launcher()
    payload = hook_input("Bash", {"stdout": DENSE})

    output, answers = await run_hook(client, await platform_session(db), tmp_path, monkeypatch, payload)

    (answer,) = answers
    assert answer["content"]["kind"] == "withhold" and answer["content"]["withheld"] == 1
    assert answer["content"]["kept_by_client"] is True, "Claude Code keeps a built-in tool's output (C12D-06)"
    assert "updated_output" not in answer["content"] and FRAGMENT not in json.dumps(answer)
    specific = output["hookSpecificOutput"]
    assert specific == {"hookEventName": "PostToolUse", "additionalContext": content_hooks.KEPT_NOTE}
    assert "withheld" not in output["systemMessage"] and "stays as it is" in output["systemMessage"]

    fake, build = gateway_setup
    headers = await build()
    newest = await client.post(MESSAGES, json=next_request(ALIAS, payload, output, answered=False), headers=headers)
    assert newest.status_code == 400 and "content_scan_unfinished" in newest.text
    assert fake.requests == []

    later = await client.post(MESSAGES, json=next_request(ALIAS, payload, output, answered=True), headers=headers)
    assert later.status_code == 400 and "content_scan_unfinished" in later.text
    assert fake.requests == [], "the original never reaches the provider"
