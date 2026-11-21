"""The app's draw.io diagrams, judged from the device's facts (the delivery workflows keep architecture,
navigation and data-flow diagrams of the app they build, as ``.drawio`` with an exported PNG in the README).

The launcher reports at the end of a changing phase (``octryx-claude`` ``diagram_facts``), for every diagram in the
style's folder: whether it is valid draw.io XML, the PNG it exported (``drawio -x -f png --scale 2``) or why not,
whether the README or a docs page references the PNG, and the box labels it did not find in the code.

- invalid XML: an error (the agent fixes it before the phase ends);
- no PNG because the draw.io CLI is missing: a warning with how to install it; ``missing_tool: error`` makes it red;
  the ``.drawio`` is committed either way;
- a PNG older than its diagram, a failed export, a PNG nothing references: warnings;
- labels not found in the code: warnings, and the reviewer's notes (a box must name a real module or screen).
"""

from __future__ import annotations

from typing import Any

from .finding import Finding

INSTALL = {"Darwin": "brew install --cask drawio", "": "install draw.io desktop (github.com/jgraph/drawio-desktop) "
                                                          "and put its drawio command on PATH"}
MAX_LABELS = 12


def install_hint(os_name: str = "") -> str:
    return INSTALL.get(os_name) or INSTALL[""]


def diagram_findings(style: dict[str, Any] | None, facts: Any) -> list[Finding]:
    general = dict((style or {}).get("general") or {})
    config = dict(general.get("diagrams") or {})
    if not config or config.get("enabled") is False or not isinstance(facts, dict):
        return []
    missing_level = "error" if general.get("missing_tool") == "error" else "warning"
    found: list[Finding] = []
    for item in facts.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if item.get("valid") is False:
            found.append(Finding("diagram_xml", path, f"not valid draw.io XML: {str(item.get('error') or '')[:200]}"))
            continue
        state = str(item.get("png_state") or "")
        png = str(item.get("png") or "")
        if state == "missing_tool":
            found.append(Finding("diagram_png", path, f"no PNG: the draw.io CLI is missing on this device "
                                                      f"({install_hint(str(facts.get('os') or ''))}); the .drawio is "
                                                      "committed without it", severity=missing_level))
        elif state == "export_failed":
            found.append(Finding("diagram_png", path, f"the PNG export failed: {str(item.get('error') or '')[:200]}",
                                 severity="warning"))
        elif state == "stale":
            found.append(Finding("diagram_png", png or path, "the PNG is older than its diagram", severity="warning"))
        if png and state in ("exported", "current") and item.get("referenced") is False:
            found.append(Finding("diagram_reference", png, "no README or docs page shows this PNG",
                                 severity="warning"))
        unmatched = [str(label) for label in item.get("unmatched") or []][:MAX_LABELS]
        if unmatched:
            found.append(Finding("diagram_labels", path, "boxes whose label is no name in the code: "
                                 + ", ".join(unmatched), severity="warning"))
    return found


def reviewer_notes(facts: Any) -> list[str]:
    """What the reviewer checks: the boxes the device found no code name for."""
    if not isinstance(facts, dict):
        return []
    return [f"{item.get('path')}: {', '.join(str(label) for label in item.get('unmatched')[:MAX_LABELS])}"
            for item in facts.get("files") or [] if isinstance(item, dict) and item.get("unmatched")]


__all__ = ["diagram_findings", "install_hint", "reviewer_notes"]
