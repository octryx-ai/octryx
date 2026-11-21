"""A governed tool call in a real agent run creates a session approval, and the approval stands even if the model would only summarize."""

import asyncio

import pytest

import app.agent.engine as engine_module
import app.agent.providers as providers_module
from app.models import Session
from app.services.chat_turn_background import drain_chat_turn_background_tasks
from app.services.session.turn_approval_state import PAUSED_TURNS_METADATA_KEY
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.tools.definitions import get_all_definitions
from app.tools.registry import TOOL_REGISTRY
from tests.conftest import ADMIN_PASSWORD

GOVERNED_TOOL = "get_current_time"


GOVERNED_TOOL_CALL = {
    "content": "",
    "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": GOVERNED_TOOL, "arguments": "{}"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
}


SUMMARY_ONLY = {
    "content": "Approval required before this command can run.",
    "tool_calls": None,
    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
}


@pytest.fixture
def scripted_turn(monkeypatch):
    """The real run_agent with a scripted provider (no network) and one approval-governed tool.

    The project approval policy (``services/tool_approval_gate.py``) requires an approval for
    the tool, so an approval can only come from the platform's dispatch gate, never from the
    model's text.
    """
    state: dict = {"script": [], "calls": 0, "executions": 0}

    async def governed_tool(params, context):
        state["executions"] += 1
        return {"utc_time_iso": "2026-09-30T00:00:00+00:00", "timezone_name": "UTC"}

    monkeypatch.setattr(TOOL_REGISTRY[GOVERNED_TOOL], "execute", governed_tool)
    original_prepare = engine_module._prepare_agent_run

    async def prepare(**kwargs):
        prepared = await original_prepare(**kwargs)
        prepared.tool_definitions = [get_all_definitions()[GOVERNED_TOOL]]
        prepared.tool_context.project_config = {
            **(prepared.tool_context.project_config or {}),
            "approval_policy": {"require_for_tools": [GOVERNED_TOOL]},
        }
        return prepared

    def provider_factory(**_kwargs):
        class _ScriptedProvider:
            async def chat(self, messages, model=None, tools=None, **_ignored):
                state["calls"] += 1
                return {**state["script"].pop(0), "model": model or ""}

            async def close(self):
                return None

        return _ScriptedProvider()

    monkeypatch.setattr(engine_module, "_prepare_agent_run", prepare)
    monkeypatch.setattr(providers_module, "get_provider", provider_factory)
    monkeypatch.setattr(engine_module, "get_provider", provider_factory)
    return state


async def _send_and_settle(client, prompt: str) -> dict:
    """Send one /chat/api turn and wait for its task and completion follow-ups."""
    send_resp = await client.post("/admin/chat/api/send", json={"prompt": prompt})
    assert send_resp.status_code == 200, send_resp.text
    session_id = send_resp.json()["selectedSession"]["id"]
    task = CHAT_RUN_TASKS.get(session_id)
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=30)
    await asyncio.wait_for(drain_chat_turn_background_tasks(session_id), timeout=30)
    final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session_id}")
    assert final_resp.status_code == 200
    return final_resp.json()


async def _pending_approvals_of(client, auth_headers, session_id: str) -> list[dict]:
    approvals_resp = await client.get("/api/v1/approvals", headers=auth_headers)
    assert approvals_resp.status_code == 200
    return [item for item in approvals_resp.json() if item["session_id"] == session_id]


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_api_approval_required_tool_call_uses_real_run_agent_and_creates_approval(
    client, db, auth_headers, scripted_turn
):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303
    scripted_turn["script"] = [GOVERNED_TOOL_CALL]

    final_payload = await _send_and_settle(client, "What time is it on the server?")
    session_id = final_payload["selectedSession"]["id"]

    assert final_payload["selectedSessionIsRunning"] is False
    assert final_payload["selectedSession"]["status"] == "pending_approval"
    assert final_payload["selectedSession"]["runStatus"] == "awaiting_approval"
    assert scripted_turn["executions"] == 0
    matching = await _pending_approvals_of(client, auth_headers, session_id)
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"
    assert matching[0]["action"] == f"Approve tool execution for {GOVERNED_TOOL}"
    assert final_payload["selectedSession"]["pendingApprovalCount"] == 1
    assert len(final_payload["selectedApprovals"]) == 1
    assert final_payload["selectedApprovals"][0]["status"] == "pending"
    # The approval is bound to the turn that asked for it, so its decision can resume that turn.
    session = await db.get(Session, session_id)
    await db.refresh(session)
    assert matching[0]["id"] in (session.metadata_ or {}).get(PAUSED_TURNS_METADATA_KEY, {})


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_chat_send_api_approval_stands_even_if_model_would_only_summarize(
    client, db, auth_headers, scripted_turn
):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303
    # After the governed call the model would only claim that approval is required; the pending
    # approval must come from the dispatch gate and must not be replaced by that summary.
    scripted_turn["script"] = [GOVERNED_TOOL_CALL, SUMMARY_ONLY]

    final_payload = await _send_and_settle(client, "What time is it on the server?")
    session_id = final_payload["selectedSession"]["id"]

    assert scripted_turn["calls"] == 1
    assert scripted_turn["script"] == [SUMMARY_ONLY]
    assert scripted_turn["executions"] == 0
    assert final_payload["selectedSession"]["status"] == "pending_approval"
    matching = await _pending_approvals_of(client, auth_headers, session_id)
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"
