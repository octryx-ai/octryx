"""The browser rule of a device workflow run, a stdlib-only copy of the server's ``browser_tools``:
loopback only, never the platform's own port, no free Playwright code."""

from __future__ import annotations

import re
from typing import Any

BROWSER_TOOL_PREFIX = "mcp__playwright__"
REFUSED_BROWSER_TOOLS = frozenset({f"{BROWSER_TOOL_PREFIX}browser_run_code_unsafe"})
REASON_BROWSER_URL = "browser_not_loopback"
REASON_BROWSER_CODE = "browser_code_refused"
_LOOPBACK = re.compile(r"^(?:https?://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?(?:[/?#].*)?|about:blank)$",
                       re.IGNORECASE)
MAX_DEPTH = 6


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


PLATFORM_URL_ENV = "OCTRYX_BASE_URL"
REASON_BROWSER_PLATFORM = "browser_platform_port"


def _loopback_port(url: str) -> int | None:
    from urllib.parse import urlsplit  # noqa: PLC0415

    try:
        parts = urlsplit(str(url or "").strip())
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None
    return port if (parts.hostname or "").lower() in ("127.0.0.1", "localhost", "::1") else None


BROWSER_EXTERNAL_ENV = "OCTRYX_BROWSER_EXTERNAL"
REASON_BROWSER_INTERNAL = "browser_internal_host"
INTERNAL_SUFFIXES = (".internal", ".local", ".lan", ".corp", ".intranet", ".localhost", ".home.arpa")
_NUMERIC_LABEL = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$", re.IGNORECASE)


def external_page(url: str, platform_url: str = "") -> bool:
    import ipaddress  # noqa: PLC0415
    from urllib.parse import urlsplit  # noqa: PLC0415

    try:
        parts = urlsplit(str(url or "").strip())
        host = (parts.hostname or "").rstrip(".").lower()
        platform = (urlsplit(str(platform_url or "").strip()).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https") or not host or host == platform:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        # A single label, an internal suffix or a numeric last label (``0x7f.1`` is 127.0.0.1 to a browser).
        return len(labels) > 1 and not host.endswith(INTERNAL_SUFFIXES) and not _NUMERIC_LABEL.match(labels[-1])
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_global


def browser_rule(tool_name: str, tool_input: dict[str, Any], *, platform_url: str | None = None,
                 external: bool | None = None) -> tuple[str, str] | None:
    import os  # noqa: PLC0415

    if tool_name in REFUSED_BROWSER_TOOLS:
        return REASON_BROWSER_CODE, ("In a workflow run the browser runs no free Playwright code; use "
                                     "browser_navigate, browser_resize, browser_snapshot, browser_take_screenshot, "
                                     "browser_click and browser_type.")
    platform_url = os.environ.get(PLATFORM_URL_ENV, "") if platform_url is None else platform_url
    external = os.environ.get(BROWSER_EXTERNAL_ENV) == "1" if external is None else external
    urls = _urls(tool_input)
    outside = [url for url in urls if not _LOOPBACK.match(url.strip())]
    if external and outside:
        refused = [url for url in outside if not external_page(url, platform_url)]
        if refused:
            return REASON_BROWSER_INTERNAL, (f"The browser opens public http(s) pages and the app on this machine, "
                                             f"not internal hosts or the platform: {refused[0][:200]}.")
        outside = []
    if not outside:
        platform = _loopback_port(platform_url)
        if platform is not None and any(_loopback_port(url) == platform for url in urls):
            return REASON_BROWSER_PLATFORM, ("In a workflow run the browser opens only the app this session started, "
                                             "not the platform on this machine; open your app's own port.")
        return None
    return REASON_BROWSER_URL, (f"In a workflow run the browser opens only the app on this machine "
                                f"(http://127.0.0.1:<port> or http://localhost:<port>), not {outside[0][:200]}.")
