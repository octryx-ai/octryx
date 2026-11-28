"""Every decision boundary with an unfinished examination: no allow, nothing forwarded."""

from __future__ import annotations

import uuid

import pytest

from app.services.content_detection import scanner
from app.services.content_detection.builtin import CandidateLimitError
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_routing.tool_results import check_tool_result
from app.services.model_gateway.litellm.errors import LiteLLMGatewayError
from app.services.policy_engine.runtime import PolicyRuntime, set_policy_runtime
from tests.agent_gateway.test_tool_execution_evidence import _post_tool_use
from tests.content_detection.content_obligations_support import DATA_TEXT, EMAIL, ROUTED
from tests.content_detection.test_tool_results import MASK_RESULTS, PHONE
from tests.model_gateway.conftest import ALIAS, gateway_config
from tests.policy_engine_support import use_custom_policies
from tests.services.agent_gateway.test_agent_gateway_control_plane import BASE, _gateway, _workspace

UNFINISHED = " ".join(f"10.9.{index // 250}.{index % 250}" for index in range(5200))


def _finishing(monkeypatch, scans: int) -> None:
    real = scanner._find
    calls = {"count": 0}

    def find(text, detectors):
        calls["count"] += 1
        if calls["count"] > scans:
            raise CandidateLimitError()
        return real(text, detectors)

    monkeypatch.setattr(scanner, "_find", find)


def _mode(mode: str) -> None:
    if mode == "none":
        set_policy_runtime(PolicyRuntime())
    else:
        use_custom_policies(MASK_RESULTS, mode=mode)


async def _chat(messages, *, admits=None):
    from app.db import core as db_core
    from app.services.content_routing.chat import apply_chat_content
    from app.services.model_gateway.litellm.alias_catalog import resolve_alias_admission
    from app.services.prompt_catalog import prompt_set_scope, resolve_prompt_set
    from tests.model_gateway.conftest import verified_admission

    config = gateway_config()
    config["litellm_gateway"]["aliases"]["approved-model"] = dict(config["litellm_gateway"]["aliases"][ALIAS],
                                                                  approved_data_categories=["pii"])
    entries = {alias: resolve_alias_admission(alias, config).entry for alias in (ALIAS, "approved-model")}
    async with db_core.async_session_factory() as db:
        prompt_set = await resolve_prompt_set(db, workspace_id=None)
    with prompt_set_scope(prompt_set):
        return await apply_chat_content(verified_admission(ALIAS, "approved-model"), entries[ALIAS], messages,
                                        admit=lambda alias: (entries[alias], None), tools=False)


@pytest.mark.parametrize("mode", ["none", "shadow", "enforce"])
@pytest.mark.asyncio
async def test_governed_chat_refuses_an_unfinished_first_examination_in_every_mode(client, mode):
    _mode(mode)
    with pytest.raises(LiteLLMGatewayError) as refused:
        await _chat([{"role": "user", "content": UNFINISHED}])
    assert refused.value.denial_reason == "content_scan_unfinished"


@pytest.mark.asyncio
async def test_governed_chat_refuses_an_unfinished_examination_after_the_mask_obligation(client, monkeypatch):
    # A policy that never looks at completeness: a Cedar allow over the unfinished second
    # examination must not let the request go on.
    policy = ROUTED.replace(f'@reroute_to("{ALIAS}")', '@reroute_to("approved-model")').replace(
        " || '\n          '(context.content.scanned && !context.content.complete)", "").replace(
        " || (context.content.scanned && !context.content.complete)", "")
    assert "content.complete" not in policy
    use_custom_policies(policy, mode="enforce")
    _finishing(monkeypatch, scans=2)  # the first examination and the masking finish, the second does not
    with pytest.raises(LiteLLMGatewayError) as refused:
        await _chat([{"role": "user", "content": DATA_TEXT}])
    assert refused.value.denial_reason == "content_scan_unfinished"
    assert EMAIL in DATA_TEXT  # the original never went on: the call raised before dispatch


@pytest.mark.asyncio
async def test_the_tool_result_check_blocks_an_unfinished_examination_after_the_mask_obligation(monkeypatch):
    use_custom_policies(MASK_RESULTS, mode="enforce")
    _finishing(monkeypatch, scans=2)
    outcome = await check_tool_result({"text": f"tel {PHONE}"}, tool_name="t", family=None, origin="connector",
                                      workspace_id="ws-1", session_id=None, conversation="chat")
    assert outcome.blocked and outcome.reason == "content_scan_unfinished"
    assert PHONE not in str(outcome.result)


@pytest.mark.parametrize("mode", ["none", "shadow", "enforce"])
@pytest.mark.asyncio
async def test_launcher_disposition_of_an_unfinished_result(client, db, mode):
    headers, _session = await _gateway(db, await _workspace(db))
    _mode(mode)
    report = {**_post_tool_use("PostToolUse", f"toolu_{uuid.uuid4().hex[:12]}"), "tool_name": "mcp__logs__tail",
              "tool_response": {"text": UNFINISHED}}
    mcp = (await client.post(f"{BASE}/sessions/tool-executed", headers=headers, json=report)).json()["content"]
    assert mcp["kind"] == "withhold" and mcp["withheld"] == 1 and not mcp["blocked"]
    assert mcp["updated_output"] == {"text": WITHHELD_TEXT}

    bash = {**report, "tool_name": "Bash", "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
            "tool_response": {"stdout": UNFINISHED}}
    builtin = (await client.post(f"{BASE}/sessions/tool-executed", headers=headers, json=bash)).json()["content"]
    assert builtin["kind"] == "withhold" and "updated_output" not in builtin
