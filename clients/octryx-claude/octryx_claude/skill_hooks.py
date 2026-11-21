"""The ``UserPromptExpansion`` hook (usage): a typed slash command is recorded by name, never blocked.

Only ``command_name`` and ``command_source`` are sent — never the prompt or the arguments. Any failure is silent:
usage reporting must never stand between the user and their command.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from .platform import SessionContext, call_control_plane
from .state import LocalState

SKILL_USED_TIMEOUT = 4.0
MAX_INPUT_BYTES = 256 * 1024


def usage_body(hook_input: dict[str, Any]) -> dict[str, str] | None:
    name = str(hook_input.get("command_name") or "").strip()
    if not name or len(name) > 100:
        return None
    return {"command_name": name, "command_source": str(hook_input.get("command_source") or "")[:40]}


def run_user_prompt_expansion(state: LocalState, http: httpx.Client) -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        hook_input = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_INPUT_BYTES else {}
        body = usage_body(hook_input) if isinstance(hook_input, dict) else None
        context = SessionContext.from_env()
        if body is not None and context is not None:
            call_control_plane(state, context, "POST", "/sessions/skill-used", http=http,
                               timeout=SKILL_USED_TIMEOUT, body=body)
    except Exception:  # noqa: BLE001 - never block a typed command
        pass
    return 0


__all__ = ["run_user_prompt_expansion", "usage_body"]
