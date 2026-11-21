"""The Confluence Cloud REST v2 fake of the publication tests and its one-shot faults (no network). No tests live here."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx

SITE = "https://your-site.atlassian.net/wiki"
API = "/wiki/api/v2"
SPACE_KEY = "DEMO"
SPACE_ID = "98304"
PARENT = "100001"


class FakeCloudV2:
    """A Confluence Cloud v2 site: spaces, pages with versions, direct children with cursor pagination."""

    def __init__(self, *, page_size: int = 250) -> None:
        self.spaces = {SPACE_ID: SPACE_KEY}
        self.pages: dict[str, dict[str, Any]] = {}
        self.extra_children: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, str]] = []
        self.page_size = page_size
        self.ids = itertools.count(50000)
        # One-shot faults by "METHOD" or "METHOD /path"; persistent overrides by "METHOD /path".
        self.faults: dict[str, Callable[[FakeCloudV2, httpx.Request], httpx.Response | None]] = {}
        self.overrides: dict[str, Callable[[FakeCloudV2, httpx.Request], httpx.Response]] = {}
        self.store: Callable[[str], str] = lambda storage: storage  # the provider's storage re-serialisation
        self.add_page("Feature documentation", "<p>Index of the features.</p>", page_id=PARENT, parent=None)

    # --- state -------------------------------------------------------------------------------------------------

    def add_page(self, title: str, storage: str, *, page_id: str | None = None, parent: str | None = PARENT,
                 space: str = SPACE_ID, status: str = "current") -> str:
        page_id = page_id or str(next(self.ids))
        self.pages[page_id] = {"id": page_id, "spaceId": space, "parentId": parent, "status": status,
                               "versions": [{"number": 1, "title": title, "storage": storage, "message": ""}]}
        return page_id

    def edit(self, page_id: str, *, storage: str | None = None, title: str | None = None,
             message: str = "human edit") -> None:
        last = self.pages[page_id]["versions"][-1]
        self.pages[page_id]["versions"].append({"number": last["number"] + 1, "title": title or last["title"],
                                                "storage": last["storage"] if storage is None else storage,
                                                "message": message})

    def children(self, parent: str) -> list[str]:
        return sorted(pid for pid, page in self.pages.items() if page["parentId"] == parent)

    @property
    def writes(self) -> list[tuple[str, str]]:
        return [request for request in self.requests if request[0] in ("POST", "PUT")]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # --- rendering ---------------------------------------------------------------------------------------------

    def page_json(self, page_id: str, *, version: int | None = None, body: bool = True) -> dict[str, Any]:
        page = self.pages[page_id]
        at = page["versions"][-1] if version is None else page["versions"][version - 1]
        data = {"id": page_id, "status": page["status"], "title": at["title"], "spaceId": page["spaceId"],
                "parentId": page["parentId"], "parentType": "page" if page["parentId"] else None,
                "version": {"number": at["number"], "message": at["message"], "createdAt": "2026-10-13T12:00:00Z"},
                "_links": {"webui": f"/spaces/{SPACE_KEY}/pages/{page_id}/{at['title'].replace(' ', '+')}"}}
        if body:
            data["body"] = {"storage": {"representation": "storage", "value": at["storage"]}}
        return data

    # --- HTTP --------------------------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url)))
        key = f"{request.method} {request.url.path}"
        if key in self.overrides:
            return self.overrides[key](self, request)
        fault = self.faults.pop(key, None) or self.faults.pop(request.method, None)
        if fault is not None:
            answer = fault(self, request)
            if answer is not None:
                return answer
        return self.route(request)

    def route(self, request: httpx.Request) -> httpx.Response:
        path, query = request.url.path, parse_qs(request.url.query.decode())
        if not path.startswith(API + "/"):
            return httpx.Response(404, json={"message": "not the v2 API"})
        parts = path[len(API) + 1:].split("/")
        if request.method == "GET" and parts == ["spaces"]:
            # Confluence matches the keys without case (``keys=COFFE`` answers the space "Coffe").
            keys = {key.upper() for key in ",".join(query.get("keys", [])).split(",")}
            return httpx.Response(200, json={"results": [{"id": sid, "key": key, "name": key}
                                                         for sid, key in self.spaces.items() if key.upper() in keys],
                                             "_links": {}})
        if request.method == "GET" and len(parts) == 2 and parts[0] == "spaces":
            if parts[1] not in self.spaces:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"id": parts[1], "key": self.spaces[parts[1]]})
        if request.method == "GET" and parts == ["pages"]:
            title, space = query.get("title", [""])[0], query.get("space-id", [""])[0]
            found = [self.page_json(pid, body=False) for pid, page in self.pages.items()
                     if page["spaceId"] == space and page["versions"][-1]["title"] == title
                     and page["status"] == "current"]
            return httpx.Response(200, json={"results": found, "_links": {}})
        if request.method == "GET" and len(parts) == 2 and parts[0] == "pages":
            if parts[1] not in self.pages:
                return httpx.Response(404, json={})
            version = int(query["version"][0]) if "version" in query else None
            if version is not None and not 1 <= version <= len(self.pages[parts[1]]["versions"]):
                return httpx.Response(404, json={})
            return httpx.Response(200, json=self.page_json(parts[1], version=version,
                                                           body="body-format" in query))
        if request.method == "GET" and len(parts) == 3 and parts[2] == "direct-children":
            return self.direct_children(parts[1], query)
        if request.method == "POST" and parts == ["pages"]:
            data = json.loads(request.content)
            if data.get("status") != "current" or data.get("spaceId") not in self.spaces:
                return httpx.Response(400, json={})
            if data.get("parentId") not in self.pages:
                return httpx.Response(404, json={})
            page_id = self.add_page(data["title"], self.store(data["body"]["value"]), parent=data["parentId"],
                                    space=data["spaceId"])
            return httpx.Response(200, json=self.page_json(page_id))
        if request.method == "PUT" and len(parts) == 2 and parts[0] == "pages":
            data = json.loads(request.content)
            page = self.pages.get(parts[1])
            if page is None:
                return httpx.Response(404, json={})
            if data["version"]["number"] != page["versions"][-1]["number"] + 1:
                return httpx.Response(409, json={"errors": [{"title": "Version must be incremented"}]})
            self.edit(parts[1], storage=self.store(data["body"]["value"]), title=data["title"],
                      message=data["version"].get("message", ""))
            return httpx.Response(200, json=self.page_json(parts[1]))
        return httpx.Response(404, json={})

    def direct_children(self, parent: str, query: dict[str, list[str]]) -> httpx.Response:
        if parent not in self.pages:
            return httpx.Response(404, json={})
        entries = [{"id": pid, "type": "page", "status": self.pages[pid]["status"],
                    "title": self.pages[pid]["versions"][-1]["title"]} for pid in self.children(parent)]
        entries += self.extra_children.get(parent, [])
        size = min(int(query.get("limit", ["25"])[0]), self.page_size)
        start = int(query.get("cursor", ["0"])[0])
        chunk = entries[start:start + size]
        links = {}
        if start + size < len(entries):
            links["next"] = f"{API}/pages/{parent}/direct-children?cursor={start + size}&limit={size}"
        return httpx.Response(200, json={"results": chunk, "_links": links})


# --- faults ----------------------------------------------------------------------------------------------------


def apply_then(error: BaseException) -> Callable[[FakeCloudV2, httpx.Request], None]:
    """The provider applies the request, then the answer is lost (``error`` raised to the client)."""

    def fault(fake: FakeCloudV2, request: httpx.Request) -> None:
        fake.route(request)
        raise error

    return fault


def raise_before(error: BaseException) -> Callable[[FakeCloudV2, httpx.Request], None]:
    def fault(_fake: FakeCloudV2, _request: httpx.Request) -> None:
        raise error

    return fault


def answer(status: int, body: Any = None, *, apply: bool = False) -> Callable[[FakeCloudV2, httpx.Request],
                                                                             httpx.Response]:
    def fault(fake: FakeCloudV2, request: httpx.Request) -> httpx.Response:
        if apply:
            fake.route(request)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body if body is not None else {})

    return fault


def read_timeout() -> httpx.ReadTimeout:
    return httpx.ReadTimeout("the answer was lost")
