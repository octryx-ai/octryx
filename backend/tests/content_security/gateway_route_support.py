"""The four gateway routes of an external coding agent, each with its captured upstream, for the gateway matrix."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.models import WorkspaceContentGovernance, WorkspaceContentHandling
from tests.agent_gateway.seat_presence_support import SEAT, _seat_headers, _seat_session
from tests.model_gateway import codex_seat_support
from tests.model_gateway import model_gateway_openai_responses_support as openai_support
from tests.model_gateway.conftest import ALIAS

ANTHROPIC_ROUTE = "/api/v1/model-gateway/anthropic/v1/messages"
SEAT_MODEL = "claude-sonnet-5"


def messages_body(model: str, *, newest: str = "Now summarize.", result: str = "3 passed",
                  tool: dict[str, Any] | None = None, history: str = "Run the tests.",
                  extra_block: dict[str, Any] | None = None,
                  arguments: dict[str, Any] | None = None, answered: bool = False) -> dict[str, Any]:
    newest_blocks: list[Any] = [{"type": "tool_result", "tool_use_id": "toolu_1", "content": result},
                                {"type": "text", "text": newest}]
    if extra_block is not None:
        newest_blocks.append(extra_block)
    return {
        "model": model, "max_tokens": 1024, "stream": True,
        "system": [{"type": "text", "text": "You are a coding agent."}],
        "tools": [tool or {"name": "Bash", "description": "Run a command", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": history},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "Run them.", "signature": "c2lnbmF0dXJl" * 8},
                {"type": "text", "text": "Running them."},
                {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": arguments or {"command": "pytest -q"}}]},
            {"role": "user", "content": newest_blocks},
            *([{"role": "assistant", "content": "Done."}, {"role": "user", "content": "Thanks."}] if answered else []),
        ],
    }


def responses_body(model: str, *, newest: str = "Now summarize.", result: str = "3 passed",
                   tool: dict[str, Any] | None = None, history: str = "Run the tests.",
                   extra_block: dict[str, Any] | None = None,
                   arguments: dict[str, Any] | None = None, answered: bool = False) -> dict[str, Any]:
    newest_parts: list[Any] = [{"type": "input_text", "text": newest}]
    if extra_block is not None:
        newest_parts.append(extra_block)
    return {
        "model": model, "instructions": "You are Codex, a coding agent.", "stream": True, "store": False,
        "tools": [tool or {"type": "function", "name": "read_ticket", "description": "Look up a ticket.",
                           "parameters": {"type": "object"}}],
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": history}]},
            {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "Run them."}],
             "encrypted_content": "b3BhcXVl" * 8},
            {"type": "function_call", "call_id": "call_1", "name": "shell",
             "arguments": json.dumps(arguments or {"command": ["pytest", "-q"]})},
            {"type": "function_call_output", "call_id": "call_1", "output": result},
            {"type": "message", "role": "user", "content": newest_parts},
            *([{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]},
               {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Thanks."}]}]
              if answered else []),
        ],
    }


@dataclass
class GatewayRoute:
    name: str
    path: str
    headers: dict[str, str]
    upstream: list[httpx.Request]
    workspace_id: str
    model: str
    responses: bool

    def body(self, **parts: Any) -> dict[str, Any]:
        build: Callable[..., dict[str, Any]] = responses_body if self.responses else messages_body
        return build(self.model, **parts)

    def tool(self, name: str, description: str) -> dict[str, Any]:
        if self.responses:
            return {"type": "function", "name": name, "description": description, "parameters": {"type": "object"}}
        return {"name": name, "description": description, "input_schema": {"type": "object"}}

    def reason(self, response: httpx.Response) -> str:
        if self.responses:
            return response.json()["error"]["code"]
        return response.headers["x-octryx-gateway-reason"]

    def sent(self) -> list[dict[str, Any]]:
        return [json.loads(item.content) for item in self.upstream]


async def configure(db, workspace_id: str, kind: str, action: str, alias: str | None = None) -> None:
    db.add(WorkspaceContentHandling(workspace_id=workspace_id, kind=kind, action=action))
    if alias is not None:
        await db.merge(WorkspaceContentGovernance(workspace_id=workspace_id, governance_alias=alias))
    await db.commit()


async def open_anthropic(gateway_setup) -> GatewayRoute:
    fake, build = gateway_setup
    headers = await build()
    return GatewayRoute("anthropic", ANTHROPIC_ROUTE, headers, fake.requests, headers["X-Octryx-Workspace"], ALIAS,
                        False)


async def open_claude_seat(client, db, anthropic) -> GatewayRoute:
    workspace_id, _user, gateway, credential = await _seat_session(client, db)
    return GatewayRoute("claude_seat", SEAT, _seat_headers(gateway, credential), anthropic.requests, workspace_id,
                        SEAT_MODEL, False)


async def open_responses(responses_setup) -> GatewayRoute:
    fake, build = responses_setup
    headers = await build()
    return GatewayRoute("responses", openai_support.ROUTE, headers, fake.requests, headers["X-Octryx-Workspace"],
                        ALIAS, True)


async def open_codex_seat(client, db, chatgpt) -> GatewayRoute:
    workspace_id, _user, gateway, credential = await codex_seat_support._codex_session(client, db)
    return GatewayRoute("codex_seat", codex_seat_support.ROUTE, codex_seat_support._headers(gateway, credential),
                        chatgpt.requests, workspace_id, codex_seat_support.MODEL, True)


__all__ = ["ANTHROPIC_ROUTE", "GatewayRoute", "configure", "messages_body", "open_anthropic", "open_claude_seat",
           "open_codex_seat", "open_responses", "responses_body"]
