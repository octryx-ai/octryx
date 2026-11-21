"""The Knowledge MCP access token's resource claim: the grant id and the bound Workspaces, as JSON."""

from __future__ import annotations

import json


def access_token_resource(raw_resource: str | None) -> dict:
    if not raw_resource:
        return {}
    try:
        value = json.loads(raw_resource)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
