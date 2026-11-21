"""Browser automation tools backed by the persistent runtime."""

from __future__ import annotations

from typing import Any

from ..services.browser_automation import browser_automation_manager
from .context import ToolContext


def _session_id(context: ToolContext, params: dict[str, Any]) -> str | None:
    return str(params.get("browser_session_id") or context.session_id or "").strip() or None


async def _execute_browser_action(
    *,
    action: str,
    params: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any]:
    payload = dict(params)
    payload.pop("browser_session_id", None)
    return await browser_automation_manager.execute(
        browser_session_id=_session_id(context, params),
        workspace_root=context.workspace_root,
        db=context.db,
        project_config=context.project_config,
        action=action,
        params=payload,
    )


class BrowserOpenUrlTool:
    name = "browser_open_url"
    description = "Open a URL in a persistent headless browser session."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="open_url", params=params, context=context)


class BrowserSnapshotTool:
    name = "browser_snapshot"
    description = "Return a browser snapshot with stable element refs for later actions."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="snapshot", params=params, context=context)


class BrowserClickTool:
    name = "browser_click"
    description = "Click an element by ref from the latest browser snapshot."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="click", params=params, context=context)


class BrowserTypeTool:
    name = "browser_type"
    description = "Type text into an element by ref from the latest browser snapshot."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="type", params=params, context=context)


class BrowserPressTool:
    name = "browser_press"
    description = "Press a keyboard key in the active browser page."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="press", params=params, context=context)


class BrowserScreenshotTool:
    name = "browser_take_screenshot"
    description = "Capture a screenshot from the active browser page."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="screenshot", params=params, context=context)


class BrowserCloseTool:
    name = "browser_close"
    description = "Close the active browser automation session."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        return await _execute_browser_action(action="close", params=params, context=context)
