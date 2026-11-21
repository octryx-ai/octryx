"""Confluence page allowlist with subtrees, excludes and whole spaces: decision, save, tools.

Tree used throughout (space SPACE1)::

    1 Home
    └── 10 Page1
        ├── 20 Page2          (included with Page1's subtree)
        │   └── 21 Page2.1
        └── 30 Page3          (excluded from Page1's subtree, with everything below)
            ├── 31 Page3.1
            └── 32 Page3.2    (own subtree entry: included again)
                └── 33 Page3.2.1

Rules: ``{id: 10, include_children, excludes: [30]}``, ``{id: 32, include_children}``.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.confluence_pages.rules import normalize_page_rules, page_decision, validate_page_rules
from app.services.tool_config.validation import validate_tool_config
from app.tools import _confluence_access
from app.tools.context import ToolContext
from app.tools.registry import execute_tool

WIKI = "https://wiki.example.test/wiki"
TREE = {  # id -> (title, parent)
    "1": ("Home", None), "10": ("Page1", "1"), "20": ("Page2", "10"), "21": ("Page2.1", "20"),
    "30": ("Page3", "10"), "31": ("Page3.1", "30"), "32": ("Page3.2", "30"), "33": ("Page3.2.1", "32"),
}
RULES = [
    {"id": "10", "space_key": "SPACE1", "enabled": True, "include_children": True, "excludes": ["30"]},
    {"id": "32", "space_key": "SPACE1", "enabled": True, "include_children": True},
]
ALLOWED = {"10", "20", "21", "32", "33"}


def _ancestors(page_id: str) -> list[str]:
    chain, parent = [], TREE[page_id][1]
    while parent:
        chain.insert(0, parent)
        parent = TREE[parent][1]
    return chain


def _decide(rules, page_id, *, space="SPACE1", allowed_spaces=("SPACE1",)):
    return page_decision(normalize_page_rules(rules), page_id=page_id,
                         space_key=space, ancestor_ids=_ancestors(page_id) if page_id in TREE else [],
                         allowed_spaces=allowed_spaces)


def test_a_subtree_with_an_exclude_cuts_the_excluded_page_and_everything_below_it():
    decided = {page_id for page_id in TREE if _decide(RULES, page_id)}
    assert decided == ALLOWED


def test_the_ancestor_order_does_not_matter():
    rules = normalize_page_rules(RULES)
    assert page_decision(rules, page_id="31", space_key="SPACE1", ancestor_ids=["30", "10", "1"]) is False
    assert page_decision(rules, page_id="21", space_key="SPACE1", ancestor_ids=["20", "1", "10"]) is True


def test_a_page_only_entry_below_an_exclusion_allows_that_page_and_nothing_below():
    rules = [*RULES[:1], {"id": "30", "space_key": "SPACE1", "enabled": True, "include_children": False}]
    assert _decide(rules, "30") is True
    assert _decide(rules, "31") is False and _decide(rules, "33") is False


def test_a_page_entry_names_its_page_by_id_and_a_disabled_one_excludes_only_that_page():
    rules = [
        {"id": "10", "enabled": True, "include_children": True},
        {"id": "30", "enabled": False},  # an excluded page whose place in the tree was not loaded
    ]
    assert _decide(rules, "30") is False
    assert _decide(rules, "31") is True, "a disabled entry cuts the page itself, not its subtree"
    assert _decide([{"id": "10", "enabled": True}], "20") is False, "a page-only entry grants no child"
    assert page_decision((), page_id="10", space_key="SPACE1") is None, "no page rules: spaces decide"


def test_entries_without_a_page_id_or_a_whole_space_are_not_rules():
    rules = normalize_page_rules(["99", {"title": "Home", "enabled": True}, {"space": "SPACE1", "id": "10"}])
    assert [rule.page_id for rule in rules] == ["10"] and rules[0].space_key == ""
    assert _decide([{"title": "Home", "enabled": True}, {"id": "10", "enabled": True}], "1") is False


def test_a_whole_space_entry_keeps_a_space_fully_readable_with_its_excludes_and_only_while_the_space_is_allowed():
    rules = [{"space_key": "SPACE2", "whole_space": True, "enabled": True, "excludes": ["500"]}, *RULES]
    assert page_decision(normalize_page_rules(rules), page_id="400", space_key="SPACE2",
                         ancestor_ids=["300"], allowed_spaces=("SPACE1", "SPACE2")) is True
    assert page_decision(normalize_page_rules(rules), page_id="501", space_key="space2",
                         ancestor_ids=["300", "500"], allowed_spaces=("SPACE1", "SPACE2")) is False
    assert page_decision(normalize_page_rules(rules), page_id="400", space_key="SPACE2",
                         ancestor_ids=["300"], allowed_spaces=("SPACE1",)) is False, "not an allowed space"
    assert _decide(rules, "31", allowed_spaces=("SPACE1", "SPACE2")) is False, "the other space keeps its rules"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([{"space_key": "SPACE1", "whole_space": True, "id": "10"}], "names a space, not a page id"),
        ([{"whole_space": True}], "needs a valid space_key"),
        ([{"id": "10", "excludes": ["30"]}], "belong to a subtree or whole_space"),
        ([{"id": "10", "include_children": True, "excludes": ["x"]}], "page ids"),
        ([{"id": "10", "include_children": True, "excludes": "30"}], "must be a list"),
        ([{"title": "no id"}], "must include id"),
        ([{"id": "10", "whole_space": "yes"}], "whole_space must be true or false"),
        ([{"space_key": "SPACE1", "whole_space": True, "enabled": False}], "cannot be disabled"),
        ("10", "must be a list"),
    ],
)
def test_a_page_allowlist_the_decision_cannot_read_is_refused_at_save(value, message):
    with pytest.raises(ValueError, match=message):
        validate_page_rules(value)
    with pytest.raises(ValueError, match=message):
        validate_tool_config("confluence", {"confluence_allowed_pages": value})


def test_the_stored_shapes_pass_validation():
    validate_tool_config("confluence", {"confluence_allowed_pages": [
        *RULES, {"space_key": "SPACE2", "whole_space": True, "enabled": True},
        {"id": "67890", "title": "Page 2", "space_key": "SPACE1", "enabled": False},
    ]})


# ---------------------------------------------------------------------------
# Chat/MCP Confluence tools: the same decision with the page's real ancestors
# ---------------------------------------------------------------------------


def _page(page_id: str) -> dict:
    title, _ = TREE[page_id]
    return {"id": page_id, "title": title, "type": "page", "space": {"key": "SPACE1"}, "version": {"number": 1},
            "ancestors": [{"id": ancestor} for ancestor in _ancestors(page_id)],
            "body": {"storage": {"value": f"<p>{title}</p>"}}, "_links": {"webui": f"/pages/{page_id}"}}


class _Wiki:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/wiki")
        expand = request.url.params.get("expand", "")
        strip = (lambda page: page) if "ancestors" in expand else (lambda page: {**page, "ancestors": []})
        if path == "/rest/api/content/search":
            return httpx.Response(200, json={"results": [strip(_page(pid)) for pid in ("21", "31", "33")]})
        if path.endswith("/descendant/page"):
            root = path.split("/")[-3]
            below = [pid for pid in TREE if root in _ancestors(pid)]
            return httpx.Response(200, json={"results": [strip(_page(pid)) for pid in below], "size": len(below)})
        if path.startswith("/rest/api/content/"):
            return httpx.Response(200, json=strip(_page(path.split("/")[-1])))
        return httpx.Response(404, json={})


def _context() -> ToolContext:
    return ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", project_config={
        "confluence_url": WIKI, "confluence_username": "svc", "confluence_password": "pw",
        "confluence_allowed_spaces": [{"space_key": "SPACE1", "enabled": True}],
        "confluence_allowed_pages": RULES,
    })


@pytest.fixture
def wiki(monkeypatch):
    fake = _Wiki()
    monkeypatch.setattr(_confluence_access, "egress_transport", lambda _connection: httpx.MockTransport(fake.handler))
    return fake


async def test_get_page_follows_the_subtree_excludes(wiki):
    allowed = await execute_tool("get_confluence_page", {"page_id": "21"}, _context())
    assert allowed.get("id") == "21" and "error" not in allowed
    refused = await execute_tool("get_confluence_page", {"page_id": "31"}, _context())
    assert "not allowed" in refused["error"]
    again = await execute_tool("get_confluence_page", {"page_id": "33"}, _context())
    assert again.get("id") == "33", "included again by its own subtree entry"


async def test_search_asks_for_ancestors_and_keeps_only_allowed_pages(wiki):
    result = await execute_tool("search_confluence", {"query": "page", "space_key": "SPACE1"}, _context())
    assert [item["id"] for item in result["results"]] == ["21", "33"]
    search = next(request for request in wiki.requests if request.url.path.endswith("/content/search"))
    assert "ancestors" in search.url.params["expand"]


async def test_listing_a_subtree_drops_the_excluded_branch(wiki):
    result = await execute_tool("list_confluence_pages", {"space_key": "SPACE1"}, _context())
    assert sorted(page["id"] for page in result["pages"]) == sorted(ALLOWED)
