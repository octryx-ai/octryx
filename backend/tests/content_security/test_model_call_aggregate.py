"""The registered provider wrapper gives structures (tool-call arguments, offered tool definitions) their aggregate
disposition before dispatch; the caller's own copies stay unchanged."""

from __future__ import annotations

import json
from typing import Any

import pytest

import app.services.content_security.model_call_outcome as model_call_module
from app.services.content_detection.masking import WITHHELD_TEXT
from tests.content_security.model_call_driver_support import DRIVERS, Harness, Reply

#: These tests call provider drivers directly: they run as the platform (``tests/support/model_call_scope_plugin.py``).
pytestmark = pytest.mark.usefixtures("platform_model_call")

SECRET = "AKIA" + "QRSTUVWXYZABCDEF"
# Every value finishes on its own; the aggregate of all of them has more candidates than a detector examines.
WIDE = {f"host_{index}": f"10.7.{index // 250}.{index % 250}" for index in range(5200)}
UNFINISHED = " ".join(f"10.8.{index // 250}.{index % 250}" for index in range(5200))


def _harness(driver_name: str, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return DRIVERS[driver_name](monkeypatch, Reply("Done."))


def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    monkeypatch.setattr(model_call_module, "record_decision", entries.append)
    return entries


async def _send(harness: Harness, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    try:
        return await harness.driver.chat(messages=messages, model=harness.model, **kwargs)
    finally:
        await harness.driver.close()


def _older_call(arguments: Any) -> list[dict[str, Any]]:
    return [{"role": "user", "content": "Inventory the hosts."},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "inventory", "arguments": arguments}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "stored"},
            {"role": "assistant", "content": "Stored."},
            {"role": "user", "content": "Summarize."}]


@pytest.mark.parametrize("serialized", [True, False], ids=["json-text", "structure"])
@pytest.mark.parametrize("driver_name", sorted(DRIVERS))
async def test_finished_leaves_with_an_unfinished_aggregate_withhold_the_replayed_arguments(driver_name, serialized,
                                                                                         monkeypatch):
    recorded = _recorded(monkeypatch)
    harness = _harness(driver_name, monkeypatch)
    messages = _older_call(json.dumps(WIDE) if serialized else dict(WIDE))
    before = json.dumps(messages, sort_keys=True)
    result = await _send(harness, messages)

    (body,) = harness.sent()
    assert "10.7.0.1" not in body and "host_1" not in body and WITHHELD_TEXT in body
    assert json.dumps(messages, sort_keys=True) == before, "local execution keeps the original arguments"
    assert result["content_obligation"]["withheld"] == 1
    (entry,) = recorded
    assert "platform:unscanned-content-withheld" in entry["determining"]
    assert entry["content"]["complete"] is False and entry["content"]["unfinished"] is True


@pytest.mark.parametrize("driver_name", sorted(DRIVERS))
async def test_a_withheld_older_history_text_leaves_the_record_incomplete(driver_name, monkeypatch):
    recorded = _recorded(monkeypatch)
    harness = _harness(driver_name, monkeypatch)
    messages = [{"role": "user", "content": UNFINISHED}, {"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "Summarize."}]
    result = await _send(harness, messages)

    (body,) = harness.sent()
    assert "10.8.0.1 " not in body and WITHHELD_TEXT in body
    assert result["content_obligation"]["withheld"] == 1
    (entry,) = recorded
    assert entry["content"]["complete"] is False and entry["content"]["unfinished"] is True


def _tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


@pytest.mark.parametrize("driver_name", sorted(DRIVERS))
async def test_offered_tool_definitions_are_masked_and_an_unfinished_one_is_not_offered(driver_name, monkeypatch):
    harness = _harness(driver_name, monkeypatch)
    wide = {"type": "object", "properties": {key: {"type": "string", "description": value}
                                             for key, value in WIDE.items()}}
    tools = [_tool("deploy", f"Deploy with the key {SECRET}.", {"type": "object", "properties": {}}),
             _tool("scan_hosts", "Scan the hosts.", wide)]
    before = json.dumps(tools, sort_keys=True)
    result = await _send(harness, [{"role": "user", "content": "Deploy."}], tools=tools)

    (body,) = harness.sent()
    assert SECRET not in body and "[SECRET #" in body and "deploy" in body
    assert "scan_hosts" not in body and "10.7.0.1" not in body
    assert json.dumps(tools, sort_keys=True) == before, "the caller's tools are unchanged"
    assert result["content_obligation"]["withheld"] == 1
