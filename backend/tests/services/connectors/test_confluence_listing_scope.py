"""Confluence listings stay inside the page allowlist below any root."""

from __future__ import annotations

import httpx
import pytest

from app.services.confluence_pages.rules import normalize_page_rules, page_decision
from app.tools import _confluence_access
from app.tools.context import ToolContext
from app.tools.registry import execute_tool

WIKI = "https://wiki.example.test/wiki"
TREE = {  # id -> (title, parent, space)
    "1": ("Home", None, "SPACE1"), "10": ("Page1", "1", "SPACE1"), "30": ("Page3", "10", "SPACE1"),
    "32": ("Page3.2", "30", "SPACE1"), "33": ("Page3.2.1", "32", "SPACE1"),
    "900": ("Secret root", None, "SPACE9"), "901": ("Secret child", "900", "SPACE9"),
}


def _ancestors(page_id: str) -> list[str]:
    chain, parent = [], TREE[page_id][1]
    while parent:
        chain.insert(0, parent)
        parent = TREE[parent][1]
    return chain


def _page(page_id: str, expand: str) -> dict:
    title, _, space = TREE[page_id]
    page: dict = {"id": page_id, "title": title, "type": "page", "version": {"number": 1}}
    if "space" in expand:
        page["space"] = {"key": space}
    if "ancestors" in expand:
        page["ancestors"] = [{"id": ancestor} for ancestor in _ancestors(page_id)]
    return page


class _Wiki:
    def __init__(self, *, descendants_fail: bool = False) -> None:
        self.descendants_fail = descendants_fail
        self.search_ids: list[str] = []
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/wiki")
        expand = request.url.params.get("expand", "")
        if path.endswith("/descendant/page"):
            if self.descendants_fail:
                return httpx.Response(503, json={})
            root = path.split("/")[-3]
            below = [_page(pid, expand) for pid in TREE if root in _ancestors(pid)]
            return httpx.Response(200, json={"results": below, "size": len(below)})
        if path == "/rest/api/content/search":
            # A server that leaves out ``ancestors`` although they were asked for: they stay unknown.
            return httpx.Response(200, json={"results": [_page(pid, "space") for pid in self.search_ids]})
        if path.endswith("/child/page"):
            parent = path.split("/")[-3]
            children = [_page(pid, expand) for pid in TREE if TREE[pid][1] == parent]
            return httpx.Response(200, json={"results": children, "size": len(children)})
        if path.startswith("/rest/api/content/"):
            return httpx.Response(200, json=_page(path.split("/")[-1], expand))
        return httpx.Response(404, json={})

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def _context(pages: list | None = None) -> ToolContext:
    config = {
        "confluence_url": WIKI, "confluence_username": "svc", "confluence_password": "pw",
        "confluence_allowed_spaces": [{"space_key": "SPACE1", "enabled": True}],
    }
    if pages is not None:
        config["confluence_allowed_pages"] = pages
    return ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", project_config=config)


@pytest.fixture
def wiki(monkeypatch):
    def install(**kwargs) -> _Wiki:
        fake = _Wiki(**kwargs)
        monkeypatch.setattr(_confluence_access, "egress_transport", lambda _c: httpx.MockTransport(fake.handler))
        return fake

    return install


async def test_a_root_in_a_space_that_is_not_allowed_lists_nothing_below_it(wiki) -> None:
    fake = wiki()
    result = await execute_tool("list_confluence_pages", {"root_page_id": "900"}, _context())
    assert "not allowed" in result["error"]
    assert "901" not in str(result) and "Secret" not in str(result)
    assert not any(path.endswith("/descendant/page") for path in fake.paths()), "nothing below is read"


async def test_a_root_the_page_rules_refuse_lists_none_of_its_descendants(wiki) -> None:
    # A legacy disabled entry refuses the root only; its descendants would pass through the whole space.
    pages = [{"space_key": "SPACE1", "whole_space": True, "enabled": True}, {"id": "30", "enabled": False}]
    wiki()
    params = {"root_page_id": "30", "space_key": "SPACE1"}
    result = await execute_tool("list_confluence_pages", params, _context(pages))
    assert "not allowed" in result["error"]
    assert "pages" not in result and "Page3.2" not in str(result)


async def test_descendants_carry_their_own_space_and_the_listing_asks_for_it(wiki) -> None:
    fake = wiki()
    result = await execute_tool("list_confluence_pages", {"root_page_id": "10"}, _context())
    assert [page["id"] for page in result["pages"]] == ["10", "30", "32", "33"]
    assert {page["space_key"] for page in result["pages"]} == {"SPACE1"}
    descendant = next(r for r in fake.requests if r.url.path.endswith("/descendant/page"))
    assert "space" in descendant.url.params["expand"].split(",")


async def test_the_child_walk_fallback_honours_an_exclude_above_the_root(wiki) -> None:
    # SPACE1 whole but Page3 and below excluded; Page3.2 alone is granted again by its own page entry.
    pages = [
        {"space_key": "SPACE1", "whole_space": True, "enabled": True, "excludes": ["30"]},
        {"id": "32", "space_key": "SPACE1", "enabled": True, "include_children": False},
    ]
    fake = wiki(descendants_fail=True)
    params = {"root_page_id": "32", "space_key": "SPACE1"}
    result = await execute_tool("list_confluence_pages", params, _context(pages))
    assert [page["id"] for page in result["pages"]] == ["32"], "33 lies below the excluded Page3"
    assert any(path.endswith("/32/child/page") for path in fake.paths()), "the fallback walk ran"


async def test_the_child_walk_fallback_lists_allowed_pages_with_their_space(wiki) -> None:
    fake = wiki(descendants_fail=True)
    result = await execute_tool("list_confluence_pages", {"root_page_id": "10"}, _context())
    assert [page["id"] for page in result["pages"]] == ["10", "30", "32", "33"]
    child = next(r for r in fake.requests if r.url.path.endswith("/child/page"))
    assert "space" in child.url.params["expand"].split(",")


async def test_child_summaries_of_a_result_with_unknown_ancestors_do_not_pass_an_exclude(wiki) -> None:
    pages = [
        {"space_key": "SPACE1", "whole_space": True, "enabled": True, "excludes": ["30"]},
        {"id": "32", "space_key": "SPACE1", "enabled": True, "include_children": False},
    ]
    fake = wiki()
    fake.search_ids = ["32"]
    params = {"query": "page", "space_key": "SPACE1", "include_child_summary": True}
    result = await execute_tool("search_confluence", params, _context(pages))
    assert [item["id"] for item in result["results"]] == ["32"], "granted by its own entry"
    assert result["results"][0]["children"] == [], "33's path above 32 is unknown; Page3 may exclude it"


def test_unfetched_ancestors_never_pass_an_entry_with_excludes() -> None:
    rules = normalize_page_rules([{"space_key": "SPACE1", "whole_space": True, "enabled": True, "excludes": ["30"]}])
    decide = lambda ancestors: page_decision(  # noqa: E731
        rules, page_id="33", space_key="SPACE1", ancestor_ids=ancestors, allowed_spaces=("SPACE1",))
    assert decide(None) is False, "not fetched: an exclude above cannot be ruled out"
    assert decide([]) is True, "a top-level page"
    assert decide(["1", "10", "30", "32"]) is False
    plain = normalize_page_rules([{"space_key": "SPACE1", "whole_space": True, "enabled": True}])
    assert page_decision(plain, page_id="33", space_key="SPACE1", ancestor_ids=None,
                         allowed_spaces=("SPACE1",)) is True, "no excludes: nothing to rule out"


def test_a_payload_without_ancestors_is_not_fetched_unlike_a_top_level_page() -> None:
    assert _confluence_access.ancestor_ids_of({"id": "1"}) is None
    assert _confluence_access.ancestor_ids_of({"id": "1", "ancestors": []}) == []
    assert _confluence_access.ancestor_ids_of({"ancestors": [{"id": 1}, {"x": 2}]}) == ["1"]
