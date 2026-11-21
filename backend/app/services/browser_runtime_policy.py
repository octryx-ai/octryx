"""Shared policy defaults for the browser runtime worker."""

from __future__ import annotations

from typing import Any

MIN_BROWSER_ACTION_TIMEOUT_MS = 1_000
DEFAULT_BROWSER_NAVIGATION_TIMEOUT_MS = 20_000
DEFAULT_BROWSER_INTERACTION_TIMEOUT_MS = 15_000
MAX_BROWSER_ACTION_TIMEOUT_MS = 120_000

MIN_BROWSER_SNAPSHOT_ELEMENTS = 1
DEFAULT_BROWSER_SNAPSHOT_ELEMENTS = 40
MAX_BROWSER_SNAPSHOT_ELEMENTS = 200
DEFAULT_BROWSER_SNAPSHOT_TEXT_PREVIEW_CHARS = 140

DEFAULT_BROWSER_WAIT_UNTIL = "domcontentloaded"
DEFAULT_BROWSER_VIEWPORT_WIDTH = 1440
DEFAULT_BROWSER_VIEWPORT_HEIGHT = 900

BROWSER_CHROMIUM_LAUNCH_ARGS = (
    "--disable-dev-shm-usage",
    "--no-sandbox",
)


def clamp_browser_timeout_ms(raw_value: Any, *, default_ms: int) -> int:
    try:
        timeout_ms = int(raw_value or default_ms)
    except (TypeError, ValueError):
        timeout_ms = default_ms
    return max(MIN_BROWSER_ACTION_TIMEOUT_MS, min(timeout_ms, MAX_BROWSER_ACTION_TIMEOUT_MS))


def clamp_browser_snapshot_elements(raw_value: Any) -> int:
    try:
        max_elements = int(raw_value or DEFAULT_BROWSER_SNAPSHOT_ELEMENTS)
    except (TypeError, ValueError):
        max_elements = DEFAULT_BROWSER_SNAPSHOT_ELEMENTS
    return max(MIN_BROWSER_SNAPSHOT_ELEMENTS, min(max_elements, MAX_BROWSER_SNAPSHOT_ELEMENTS))


def normalize_browser_wait_until(raw_value: Any) -> str:
    value = str(raw_value or DEFAULT_BROWSER_WAIT_UNTIL).strip()
    return value or DEFAULT_BROWSER_WAIT_UNTIL


def build_browser_context_kwargs(user_agent: str | None = None) -> dict[str, Any]:
    context_kwargs: dict[str, Any] = {
        "viewport": {
            "width": DEFAULT_BROWSER_VIEWPORT_WIDTH,
            "height": DEFAULT_BROWSER_VIEWPORT_HEIGHT,
        }
    }
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    return context_kwargs
