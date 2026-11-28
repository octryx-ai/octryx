"""The relay's stdout events read for the bridge: the cross-session messages sessions sent to the phone, the relay's
own SendMessage calls and their results (``mobile_relay``)."""

from __future__ import annotations

import re
from typing import Any

MAX_TEXT = 8000
INCOMING = re.compile(
    r'<cross-session-message from="(?P<from>[^"]{1,300})"(?: from-name="(?P<name>[^"]{0,200})")?[^>]*>\n?'
    r"(?P<body>.*?)\n?</cross-session-message>",
    re.S,
)


def parse_incoming(event: dict[str, Any]) -> list[tuple[str, str, str]]:
    if not isinstance(event, dict) or event.get("type") != "user":
        return []
    origin = event.get("origin") if isinstance(event.get("origin"), dict) else {}
    if origin.get("kind") != "peer" and (event.get("isReplay") or event.get("isSynthetic")):
        # Our own request echoed back (it may quote anything the person typed) or a nudge of Claude Code. A
        # session's message to the relay is injected too (replayed, synthetic) but carries ``origin.kind: peer``.
        return []
    content = (event.get("message") or {}).get("content")
    texts = [content] if isinstance(content, str) else [
        part.get("text", "") for part in content or [] if isinstance(part, dict) and part.get("type") == "text"]
    found = []
    for text in texts:
        for match in INCOMING.finditer(text or ""):
            found.append((match["from"], match["name"] or "", match["body"].strip()[:MAX_TEXT]))
    return found


def sent_calls(event: dict[str, Any]) -> list[tuple[str, str, str]]:
    if not isinstance(event, dict) or event.get("type") != "assistant":
        return []
    out = []
    for block in (event.get("message") or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "SendMessage":
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            out.append((str(block.get("id") or ""), str(tool_input.get("to") or ""),
                        str(tool_input.get("message") or "")))
    return out


def tool_results(event: dict[str, Any]) -> list[tuple[str, bool]]:
    if not isinstance(event, dict) or event.get("type") != "user":
        return []
    content = (event.get("message") or {}).get("content")
    return [(str(part.get("tool_use_id") or ""), not part.get("is_error"))
            for part in content if isinstance(part, dict) and part.get("type") == "tool_result"] \
        if isinstance(content, list) else []
