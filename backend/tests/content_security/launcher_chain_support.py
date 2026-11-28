"""The launcher's PostToolUse hook against the real platform route, and the next model request Claude Code sends
(a built-in tool's output stays in the transcript whatever the hook's disposition)."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.services.content_detection.masking import WITHHELD_TEXT

CLIENT_DIR = Path(__file__).resolve().parents[3] / "clients" / "octryx-claude"
BASE_URL = "https://platform.example.test"
TEXT = "deploy notes for 10.11.0.1"
TOOL_EXECUTED = "/api/v1/agent-gateway/sessions/tool-executed"
MESSAGES = "/api/v1/model-gateway/anthropic/v1/messages"


def launcher():
    if str(CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(CLIENT_DIR))
    from octryx_claude import content_hooks, post_tool_use_hook
    from octryx_claude.oauth import SCOPES
    from octryx_claude.state import LocalState
    from octryx_claude.tokens import GATEWAY_AUDIENCE

    return post_tool_use_hook, content_hooks, LocalState, SCOPES, GATEWAY_AUDIENCE


def hook_input(tool: str, response: Any) -> dict[str, Any]:
    return {"hook_event_name": "PostToolUse", "session_id": str(uuid.uuid4()), "tool_name": tool,
            "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}", "tool_input": {"command": "cat deploy.log"},
            "tool_response": response}


async def platform_session(db) -> dict[str, str]:
    from tests.services.agent_gateway.test_agent_gateway_control_plane import _gateway, _workspace

    headers, _session = await _gateway(db, await _workspace(db))
    return headers


async def run_hook(client, headers: dict[str, str], tmp_path: Path, monkeypatch,
                   payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    post_tool_use_hook, _content_hooks, local_state, scopes, audience = launcher()
    root = tmp_path / f"octryx-{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("OCTRYX_CLAUDE_HOME", str(root))
    state = local_state(root).ensure()
    state.write_credentials({"base_url": BASE_URL, "client_id": "oec_test", "refresh_token": "refresh-1",
                             "redirect_uri": "http://127.0.0.1:50000/callback", "scopes": sorted(scopes.split()),
                             "tokens": {audience: {"access_token": "launcher-token", "expires_at": time.time() + 3600}}})
    monkeypatch.setenv("OCTRYX_BASE_URL", BASE_URL)
    monkeypatch.setenv("OCTRYX_SESSION_KEY", headers["X-Octryx-Session"])
    monkeypatch.setenv("OCTRYX_WORKSPACE_ID", headers["X-Octryx-Workspace"])
    loop = asyncio.get_running_loop()
    answers: list[dict[str, Any]] = []

    def forward(request: httpx.Request) -> httpx.Response:
        sent = {**dict(request.headers), "authorization": headers["Authorization"]}
        sent.pop("content-length", None)
        response = asyncio.run_coroutine_threadsafe(
            client.request(request.method, request.url.path, content=request.content, headers=sent), loop).result()
        if request.url.path.endswith("/sessions/tool-executed"):
            answers.append(response.json())
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))

    stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()))
    stdout = io.StringIO()

    def hook() -> int:
        saved = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin, stdout
        try:
            return post_tool_use_hook.run_post_tool_use(state, httpx.Client(transport=httpx.MockTransport(forward)))
        finally:
            sys.stdin, sys.stdout = saved

    assert await asyncio.to_thread(hook) == 0
    printed = stdout.getvalue()
    return (json.loads(printed) if printed else None), answers


def next_request(alias: str, payload: dict[str, Any], output: dict[str, Any] | None, *,
                 answered: bool) -> dict[str, Any]:
    stdout = payload["tool_response"].get("stdout") if isinstance(payload["tool_response"], dict) else None
    content = [{"type": "tool_result", "tool_use_id": payload["tool_use_id"],
                "content": stdout if isinstance(stdout, str) else json.dumps(payload["tool_response"])}]
    context = ((output or {}).get("hookSpecificOutput") or {}).get("additionalContext")
    if context:
        content.append({"type": "text", "text": context})
    messages = [{"role": "user", "content": "check the deploy"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": payload["tool_use_id"],
                                                   "name": payload["tool_name"],
                                                   "input": payload["tool_input"]}]},
                {"role": "user", "content": content}]
    if answered:
        messages += [{"role": "assistant", "content": "Checked."}, {"role": "user", "content": "next step"}]
    return {"model": alias, "max_tokens": 64, "stream": True, "messages": messages}


REFUSING_KINDS = frozenset({"withhold", "block"})


def _refusing(content: dict[str, Any], tool: str) -> None:
    assert content["kind"] in REFUSING_KINDS and content["reason"] == "content_scan_unfinished"
    if tool.startswith("mcp__") and not content["blocked"]:
        assert content["updated_output"] == {"text": WITHHELD_TEXT}
    else:
        assert "updated_output" not in content
    assert TEXT not in json.dumps(content)


async def launcher_route_case(fx) -> None:
    headers = await platform_session(fx.db)
    for tool, response in (("mcp__logs__tail", {"text": TEXT}), ("Bash", {"stdout": TEXT})):
        answer = await fx.client.post(TOOL_EXECUTED, headers=headers, json=hook_input(tool, response))
        assert answer.status_code == 200
        _refusing(answer.json()["content"], tool)


async def launcher_disposition_case(fx) -> None:
    _hook, content_hooks, *_rest = launcher()
    headers = await platform_session(fx.db)
    for tool, response in (("mcp__logs__tail", {"text": TEXT}), ("Bash", {"stdout": TEXT})):
        answer = (await fx.client.post(TOOL_EXECUTED, headers=headers, json=hook_input(tool, response))).json()
        output = content_hooks.content_output(answer, tool)
        specific = output["hookSpecificOutput"]
        blocked = answer["content"]["blocked"]
        if not tool.startswith("mcp__"):  # Claude Code keeps a built-in tool's output: nothing claims withholding
            assert answer["content"]["kept_by_client"] is True and not blocked
            assert specific["additionalContext"] == content_hooks.KEPT_NOTE
        else:
            assert specific["additionalContext"] == (content_hooks.BLOCKED_NOTE if blocked
                                                     else content_hooks.WITHHELD_NOTE)
        if tool.startswith("mcp__") and not blocked:
            assert specific["updatedMCPToolOutput"] == {"text": WITHHELD_TEXT}
        else:
            assert "updatedMCPToolOutput" not in specific
        assert TEXT not in json.dumps(output)


async def launcher_hook_case(fx) -> None:
    from tests.model_gateway.conftest import ALIAS

    _hook, content_hooks, *_rest = launcher()
    headers = await platform_session(fx.db)
    payload = hook_input("Bash", {"stdout": TEXT})
    output, answers = await run_hook(fx.client, headers, fx.tmp_path, fx.monkeypatch, payload)
    (answer,) = answers
    _refusing(answer["content"], "Bash")
    assert output["hookSpecificOutput"]["additionalContext"] == content_hooks.KEPT_NOTE
    fake, build = fx.gateway
    gateway_headers = await build()
    for answered in (False, True):
        response = await fx.client.post(MESSAGES, json=next_request(ALIAS, payload, output, answered=answered),
                                        headers=gateway_headers)
        assert response.status_code == 400 and "content_scan_unfinished" in response.text
    assert fake.requests == []
