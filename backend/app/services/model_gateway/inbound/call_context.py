"""Client correlation context and refusal rendering shared by the inbound routes (``service``, the seat routes)."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from fastapi.responses import Response

from ...agent_gateway.identity import GatewayRefusal
from .refusals import InboundRefusal, anthropic_error_response, refusal

CLIENT_CONTEXT_HEADERS = {
    "x-claude-code-session-id": "claude_session_id",
    "x-claude-code-agent-id": "claude_agent_id",
    "x-claude-code-request-class": "claude_request_class",
}
_CONTEXT_VALUE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")

# Renders a refusal in the client's API shape (Anthropic here, OpenAI on the ``/openai`` route).
ErrorRenderer = Callable[[InboundRefusal], Response]


def render_refusal(item: InboundRefusal | GatewayRefusal, render: ErrorRenderer = anthropic_error_response) -> Response:
    if isinstance(item, GatewayRefusal):
        item = refusal(item.state, item.reason, http_status=item.http_status)
    return render(item)


def client_context(headers: Mapping[str, str], names: Mapping[str, str] = CLIENT_CONTEXT_HEADERS) -> dict[str, str]:
    """The client's own correlation headers (``names``: header -> context key), kept only when well-formed."""

    return {
        key: value
        for header, key in names.items()
        if _CONTEXT_VALUE.match(value := str(headers.get(header) or ""))
    }


__all__ = [
    "CLIENT_CONTEXT_HEADERS",
    "ErrorRenderer",
    "client_context",
    "render_refusal",
]
