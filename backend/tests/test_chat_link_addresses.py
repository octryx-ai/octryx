"""Every ``/chat?`` link the backend produces opens a page of the chat shell.

The chat shell's URL contract is ``/chat?area=<area>&tab=<page>`` plus the page's own focus parameters
(``frontend/chat/src/chat/areaNavigation.ts``); a link without ``area`` opens the chat itself. The known areas and,
for the admin-shell areas and My settings, their pages are read from the frontend's own configuration, so a link
to a removed area or page (or an address the shell never reads, such as ``view=users``) fails here.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.problems import links

REPO = Path(__file__).resolve().parents[2]
BACKEND_APP = REPO / "backend" / "app"
FRONTEND_SRC = REPO / "frontend" / "chat" / "src"
# A ``/chat?`` address inside Python or template source; ``/admin/chat?`` is another page and not matched.
LINK = re.compile(r"(?<![\w/])/chat\?[^\s\"'<>`]*")
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}|\{[^}]*\}")
# What a link without ``area`` (the chat) may carry.
CHAT_PARAMS = {"session_id", "workspace_id", "new"}


def _read(relative: str) -> str:
    return (FRONTEND_SRC / relative).read_text(encoding="utf-8")


def _known_areas() -> set[str]:
    block = re.search(r"const AREAS[^=]*=\s*new Set<WorkspaceArea>\(\[(.*?)\]\)", _read("chat/areaNavigation.ts"),
                      re.S)
    assert block, "areaNavigation.ts no longer declares its AREAS set"
    return set(re.findall(r'"(\w+)"', block.group(1)))


def _admin_shell_tabs() -> dict[str, set[str]]:
    source = _read("admin/config/adminPanelAreas.ts")
    configs = source[source.index("export const ADMIN_AREA_CONFIGS"):source.index("export const ADMIN_AREA_KEYS")]
    tabs: dict[str, set[str]] = {}
    for area, body in re.findall(r"^  (\w+): \{\n(.*?)^  \},", configs, re.S | re.M):
        tabs[area] = set(re.findall(r'\bid: "(\w+)"', body))
    entries = _read("admin/config/adminEntries.ts")
    tabs["admin"] = tabs.get("admin", set()) | set(re.findall(r'\b(?:tab: |page\()"(\w+)"', entries)) | {
        tab for also in re.findall(r"\[(\"\w+\"(?:, \"\w+\")*)\]\)", entries) for tab in re.findall(r'"(\w+)"', also)}
    assert {"knowledge", "workflows", "operations", "admin"} <= set(tabs), tabs.keys()
    return tabs


def _personal_tabs() -> set[str]:
    union = re.search(r"export type PersonalTab = ([^;]+);", _read("chat/devices/personalSettingsTab.ts"))
    assert union, "personalSettingsTab.ts no longer declares PersonalTab"
    return set(re.findall(r'"(\w+)"', union.group(1)))


def _work_pages() -> set[str]:
    """The ``work_view`` names the Work area reads (``workNavRedirects.ts``) plus its full-width Spec Studio view."""
    block = re.search(r"const ADDRESSES[^=]*=\s*\{(.*?)\n\};", _read("chat/work/workNavRedirects.ts"), re.DOTALL)
    assert block, "workNavRedirects.ts no longer declares its ADDRESSES"
    studio = re.search(r'SPEC_STUDIO_VIEW = "(\w+)"', _read("chat/specStudio/specStudioAddress.ts"))
    assert studio, "specStudioAddress.ts no longer declares SPEC_STUDIO_VIEW"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE)) | {studio.group(1)}


def _source_links() -> list[tuple[str, str]]:
    found = []
    for path in sorted(BACKEND_APP.rglob("*")):
        if path.suffix not in {".py", ".html"} or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            if text[match.end():match.end() + 1] == "<":
                continue  # the URL contract in prose (``/chat?area=<area>``), not a link
            found.append((str(path.relative_to(REPO)), PLACEHOLDER.sub("x", match.group(0))))
    return found


def _problem_links() -> list[tuple[str, str]]:
    targets = [getattr(links, name) for name in links.__all__ if name.startswith("TARGET_")]
    return [(f"problems.links:{target}", links.fix_link(target, workspace_id="w", object_id="o")["href"])
            for target in targets]


def _problem(link: str, areas: set[str], tabs: dict[str, set[str]]) -> str | None:
    params = parse_qs(urlsplit(link).query, keep_blank_values=True)
    if "view" in params:
        return "the chat shell reads no top-level view parameter"
    area = (params.get("area") or [None])[0]
    if area is None:
        extra = set(params) - CHAT_PARAMS
        return f"a chat link carries {sorted(extra)} without an area" if extra else None
    if area not in areas:
        return f"unknown area {area!r}"
    tab = (params.get("tab") or [None])[0]
    if tab is not None and area in tabs and tab not in tabs[area]:
        return f"area {area!r} has no page {tab!r}"
    work_view = (params.get("work_view") or [None])[0]
    if work_view is not None and work_view not in _work_pages():
        return f"Work has no page {work_view!r}"
    if "coding_session_id" in params:
        return "a Coding session is addressed by work_item_id"
    return None


def test_the_frontend_configuration_is_readable():
    areas = _known_areas()
    assert {"chat", "work", "admin", "operations", "personal"} <= areas
    assert "usage" in _admin_shell_tabs()["operations"] and "users" in _admin_shell_tabs()["admin"]


def test_every_backend_chat_link_resolves_to_a_known_area_and_page():
    areas = _known_areas()
    tabs = {**_admin_shell_tabs(), "personal": _personal_tabs()}
    produced = _source_links() + _problem_links()
    assert len(produced) > 20, "the scan found the backend's links"
    problems = [f"{where}: {link} ({problem})" for where, link in produced
                if (problem := _problem(link, areas, tabs))]
    assert problems == []


@pytest.mark.parametrize(("link", "expected"), [
    ("/chat?view=users", "the chat shell reads no top-level view parameter"),
    ("/chat?area=teams", "unknown area 'teams'"),
    ("/chat?area=operations&tab=users", "area 'operations' has no page 'users'"),
    ("/chat?task_id=x", "a chat link carries ['task_id'] without an area"),
    ("/chat?area=work&work_view=syncSettings", "Work has no page 'syncSettings'"),
    ("/chat?area=coding&coding_session_id=x", "a Coding session is addressed by work_item_id"),
])
def test_a_link_the_shell_cannot_open_is_named(link, expected):
    tabs = {**_admin_shell_tabs(), "personal": _personal_tabs()}
    assert _problem(link, _known_areas(), tabs) == expected
