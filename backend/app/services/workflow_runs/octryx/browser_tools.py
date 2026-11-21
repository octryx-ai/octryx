"""The browser of a run phase: the agent drives the app it builds, on this machine only.

The implement session looks at the app it builds the way a user does, through
Microsoft's Playwright MCP server (``@playwright/mcp``), which the launcher starts for that one session with a browser
instance of its own (headless, in-memory profile, no extension, never the person's Chrome; ``octryx-claude``
``browser_mcp``). Its tools (``mcp__playwright__browser_*``) are no file, shell or platform tool, so the capability
decision refused them as unclassified. In a running phase they are allowed, with two rules:

- every ``url`` the call names (also nested) is the app on loopback (``127.0.0.1``, ``localhost``, ``::1``) or a blank
  page. The server's own ``--allowed-origins`` says the same, but its README says it "does not serve as a security
  boundary"; this rule is the boundary;
- ``browser_run_code_unsafe`` (arbitrary Playwright code in the server's Node process, which can open any page and read
  any file the person can) is refused: navigate, resize, snapshot, screenshot, click and type cover a screen check.

Allowed by default: with the Workspace's ``tool_defaults.browser: read_external`` (the default) the
browser may also open public web pages to read them, logged as allowed by default. Private and internal addresses
(RFC 1918, link-local and cloud metadata, carrier-grade NAT, IPv6 unique and link-local, ``.internal``, ``.local``,
``.lan``, ``.corp``, ``.intranet``, ``.home.arpa``, single-label names), hosts with a ``prod`` label, other schemes
and free Playwright code stay refused; ``loopback`` restores the rule above.

The Claude-in-Chrome extension route (``claude --chrome`` in an agent Chrome profile) is dropped: it needed an
extension installed in a profile by hand and could drive the person's own Chrome.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

from ...agent_gateway.tool_check import DECISION_DENY, ToolDecision, allowed_by_default, setting_remedy

BROWSER_SERVER = "playwright"
BROWSER_TOOL_PREFIX = f"mcp__{BROWSER_SERVER}__"
REFUSED_BROWSER_TOOLS = frozenset({f"{BROWSER_TOOL_PREFIX}browser_run_code_unsafe"})
REASON_BROWSER_URL = "browser_not_loopback"
REASON_BROWSER_CODE = "browser_code_refused"
_LOOPBACK = re.compile(r"^(?:https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?(?:[/?#].*)?|about:blank)$",
                       re.IGNORECASE)
MAX_DEPTH = 6


def is_browser_tool(tool_name: str) -> bool:
    return str(tool_name or "").startswith(BROWSER_TOOL_PREFIX)


def _urls(value: Any, depth: int = 0) -> list[str]:
    if depth > MAX_DEPTH:
        return ["<too deep>"]
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            if str(key).lower() in ("url", "href") and not isinstance(item, (dict, list)):
                found.append(str(item))
            else:
                found.extend(_urls(item, depth + 1))
        return found
    if isinstance(value, list):
        return [url for item in value for url in _urls(item, depth + 1)]
    return []


INTERNAL_SUFFIXES = (".internal", ".local", ".lan", ".corp", ".intranet", ".home.arpa", ".localhost")
_LABEL_SPLIT = re.compile(r"[.-]")


def public_url(url: str) -> bool:
    """An http(s) URL of a public host: no private, internal, loopback or ``prod`` address."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        parts.port  # noqa: B018 - raises on an invalid port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if "." not in host or host == "localhost" or host.endswith(INTERNAL_SUFFIXES):
        return False
    return "prod" not in _LABEL_SPLIT.split(host)


def browser_tool_decision(tool_name: str, tool_input: dict[str, Any],
                          defaults: dict[str, Any] | None = None) -> ToolDecision | None:
    """``None`` (no objection) for a browser call that stays on loopback; with ``tool_defaults.browser:
    read_external`` an allow by default for public pages; a denial otherwise."""
    if tool_name in REFUSED_BROWSER_TOOLS:
        return ToolDecision(DECISION_DENY, "denied", REASON_BROWSER_CODE, REASON_BROWSER_CODE.replace("_", "-"),
                            "In a workflow run the browser runs no free Playwright code; use browser_navigate, "
                            "browser_resize, browser_snapshot, browser_take_screenshot, browser_click and "
                            "browser_type.")
    outside = [url for url in _urls(tool_input) if not _LOOPBACK.match(url.strip())]
    if not outside:
        return None
    external = defaults is not None and defaults.get("browser", "read_external") == "read_external"
    if external and all(public_url(url) for url in outside):
        return allowed_by_default("browser")
    if external:
        return ToolDecision(DECISION_DENY, "denied", REASON_BROWSER_URL, REASON_BROWSER_URL.replace("_", "-"),
                            f"In a workflow run the browser opens the app on this machine and public web pages, not "
                            f"internal or production addresses such as {outside[0][:200]}.")
    return ToolDecision(DECISION_DENY, "denied", REASON_BROWSER_URL, REASON_BROWSER_URL.replace("_", "-"),
                        f"In a workflow run the browser opens only the app on this machine (http://127.0.0.1:<port> "
                        f"or http://localhost:<port>), not {outside[0][:200]}."
                        + (" A Workspace admin can allow public pages (Workspace settings › Coding tools & devices"
                           " › Tool defaults)."
                           if defaults is not None else ""),
                        remedy=setting_remedy("browser", "read_external") if defaults is not None else None)


__all__ = ["BROWSER_SERVER", "BROWSER_TOOL_PREFIX", "REFUSED_BROWSER_TOOLS", "browser_tool_decision",
           "is_browser_tool"]
