"""A browser of its own in one device phase (``config.browser: true``, opt-in per node)."""

from __future__ import annotations

from typing import Any

from .browser_tools import BROWSER_TOOL_PREFIX

BROWSER_KEY = "browser"
BROWSER_NOTE = {
    "hosts": ["127.0.0.1", "localhost"],
    "tools": f"{BROWSER_TOOL_PREFIX}*",
    "rule": ("This phase has a browser of its own (mcp__playwright__browser_*: a headless Chrome for this session "
             "only). Open the app only on 127.0.0.1 or localhost, look at its screens once at browser_resize 1280x800 "
             "and 390x844 (browser_snapshot for text and structure, browser_take_screenshot without a filename to see "
             "it) and fix what misses the specification's design section. When the browser tools are not there, take "
             "Playwright screenshots instead."),
}


def node_allows_browser(node: Any) -> bool:
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(BROWSER_KEY) is True


async def phase_allows_browser(db: Any, run: Any, node: Any) -> bool:
    if node is None:
        return False
    if node_allows_browser(node):
        return True
    from ..graph import NODE_PHASE

    if run is None or not getattr(run, "project_id", None) or getattr(node, "kind", None) != NODE_PHASE:
        return False
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import browser_phase_key, device_runs_section

    loaded = await load_workspace_policy(db, run.project_id)
    section = device_runs_section(loaded.policy.raw) if loaded.policy is not None else {}
    return browser_phase_key(str(run.workflow_key or ""), str(node.id)) in set(section.get("browser_phases") or [])


__all__ = ["BROWSER_KEY", "BROWSER_NOTE", "node_allows_browser", "phase_allows_browser"]
