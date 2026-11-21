"""
Mock Bot Framework Connector Server
=====================================
Listens on http://localhost:3980 and receives the outbound replies that
Octryx sends back to "Teams" during local development.

When Octryx processes a message it calls:
    POST {serviceUrl}/v3/conversations/{convId}/activities/{actId}

By setting serviceUrl to http://localhost:3980 in send_test_message.py,
all replies land here and are printed to the terminal — no real Teams or
Azure credentials needed.

Usage:
    python dev/mock_bf_server.py
"""

import json
import logging
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("mock-bf")

REPLY_COUNT = 0


async def handle_reply(request: web.Request) -> web.Response:
    global REPLY_COUNT
    body = await request.json()
    REPLY_COUNT += 1

    conv_id = request.match_info.get("conv_id", "?")
    act_id = request.match_info.get("act_id", "?")
    text = body.get("text", "")

    border = "─" * 60
    print(f"\n{border}")
    print(f"  REPLY #{REPLY_COUNT}  (conv={conv_id[:20]}…  replyTo={act_id[:12]}…)")
    print(border)
    print(f"\n{text}\n")
    print(border)

    return web.Response(
        status=200,
        content_type="application/json",
        text=json.dumps({"id": f"mock-reply-{REPLY_COUNT}"}),
    )


async def handle_token(request: web.Request) -> web.Response:
    """Fake token endpoint so Octryx doesn't fail when it tries to get a BF token."""
    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "access_token": "mock-token-for-local-dev",
            "token_type": "Bearer",
            "expires_in": 3600,
        }),
    )


def create_app() -> web.Application:
    app = web.Application()
    # Outbound reply from Octryx
    app.router.add_post(
        "/v3/conversations/{conv_id}/activities/{act_id}",
        handle_reply,
    )
    app.router.add_post(
        "/v3/conversations/{conv_id}/activities",
        handle_reply,
    )
    return app


if __name__ == "__main__":
    print("Mock Bot Framework Connector listening on http://localhost:3980")
    print("Octryx replies will be printed here.\n")
    web.run_app(create_app(), host="127.0.0.1", port=3980)
