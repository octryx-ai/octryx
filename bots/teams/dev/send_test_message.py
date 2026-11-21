"""
Send a fake Teams Bot Framework activity to the local Octryx webhook.
=================================================================
Simulates exactly what Microsoft Teams sends to the bot — no Azure account,
no ngrok, no real Teams needed.

The serviceUrl points to mock_bf_server.py (localhost:3980) so Octryx can reply
and you'll see the answer printed there.

Usage:
    # Terminal 1 – run Octryx backend (with msteams plugin enabled, any credentials) with
    #   DEBUG=true OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED=true (unsigned activities)
    # Terminal 2 – run mock BF server:
    python dev/mock_bf_server.py
    # Terminal 3 – send a test message:
    python dev/send_test_message.py --channel-id 2 "What can you do?"
    python dev/send_test_message.py --channel-id 2 --sender alice "Summarise the latest report"

Options:
    --channel-id DB channel id (required)
    --octryx-url    Octryx base URL          (default: http://localhost:8000)
    --sender    Fake Teams sender ID (default: local-dev-user)
    --conv      Fake conversation ID (default: auto-generated)
    --bf-url    Mock BF server URL   (default: http://localhost:3980)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import httpx


def build_activity(text: str, sender_id: str, conv_id: str, bf_url: str) -> dict:
    """Build a minimal Bot Framework message activity."""
    return {
        "type": "message",
        "id": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "serviceUrl": bf_url,
        "channelId": "msteams",
        "from": {
            "id": sender_id,
            "aadObjectId": sender_id,
            "name": f"Dev User ({sender_id})",
        },
        "conversation": {
            "id": conv_id,
            "conversationType": "personal",
            "isGroup": False,
        },
        "recipient": {
            "id": "28:local-bot-id",
            "name": "Octryx Bot",
        },
        "text": text,
        "locale": "en-US",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test Teams message to local Octryx")
    parser.add_argument("text", nargs="?", default="Hello, what can you do?")
    parser.add_argument("--octryx-url", default="http://localhost:8000")
    parser.add_argument("--sender", default="local-dev-user")
    parser.add_argument("--conv", default=None)
    parser.add_argument("--bf-url", default="http://localhost:3980")
    parser.add_argument("--channel-id", required=True, help="DB channel_id (e.g. 2).")
    args = parser.parse_args()

    conv_id = args.conv or f"local-conv-{args.sender}"
    activity = build_activity(args.text, args.sender, conv_id, args.bf_url)

    base = args.octryx_url.rstrip("/")
    webhook_url = f"{base}/api/v1/channels/msteams/{args.channel_id}/webhook"

    print(f"→ Sending to {webhook_url}")
    print(f"  sender : {args.sender}")
    print(f"  conv   : {conv_id}")
    print(f"  text   : {args.text}")
    print(f"  reply→ : {args.bf_url}")
    print()

    # No Authorization header: Octryx accepts this only when the backend runs with DEBUG=true and
    # OCTRYX_CHANNEL_WEBHOOK_DEV_UNAUTHENTICATED=true (machine-local stack); otherwise it
    # answers 401 channel_webhook_unauthenticated.
    resp = httpx.post(
        webhook_url,
        content=json.dumps(activity),
        headers={"Content-Type": "application/json"},
        timeout=10.0,
    )

    if resp.status_code == 200:
        print(f"✓ Webhook accepted (HTTP {resp.status_code}) — watch mock_bf_server for the reply")
    else:
        print(f"✗ Webhook returned HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
