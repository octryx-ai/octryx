"""A browser of its own in one device phase (``config.browser: true``, opt-in per node).

The story session of epic-delivery opens the app it builds, looks at every screen at desktop and
phone width and fixes what misses the specification's design section before the independent review (reviews
find flat cards and missing states that a look at the screen shows at once).

A flagged phase's job offer carries ``browser: true``: the launcher adds Microsoft's Playwright MCP server
(``@playwright/mcp``, pinned, installed once in the launcher's own folder) to that turn's MCP config only. The server
starts its own headless browser instance with an in-memory profile per session (``--isolated``): no extension, never
the person's Chrome or profile. Every other turn has no browser. The platform's PreToolUse rule keeps every URL on
loopback and refuses free Playwright code (``browser_tools``).

A Workspace switches the browser on for named phases of its runs
(``device_runs.browser_phases``, ``"<workflow_key>.<node_id>"``), also over a node's ``browser: false`` (the
epic-delivery seed ships ``implement`` without it): :func:`phase_allows_browser` decides for a run's phase, and the
job offer and the contract's ``phase.browser`` note both follow it.

The Claude-in-Chrome route (``claude --chrome`` in an agent Chrome profile) is
dropped; it needed the extension installed by hand in that profile and could drive the person's own Chrome.
"""

from __future__ import annotations

from typing import Any

from .browser_tools import BROWSER_TOOL_PREFIX

BROWSER_KEY = "browser"
#: The phase contract's note: what the agent may do with the browser (``contract.phase.browser``).
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
    """Whether a phase node opted in (``config.browser`` is exactly ``true``)."""
    config = getattr(node, "config", None)
    return isinstance(config, dict) and config.get(BROWSER_KEY) is True


async def phase_allows_browser(db: Any, run: Any, node: Any) -> bool:
    """Whether ``run``'s turn in phase ``node`` gets a browser: the node opted in, or the run's Workspace lists the
    phase in ``device_runs.browser_phases`` (the Workspace's list wins over the node's ``browser: false``)."""
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
