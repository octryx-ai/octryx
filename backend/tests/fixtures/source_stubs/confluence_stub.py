"""A read-only Confluence Server/DC REST stub for the source-ACL acceptance check (K6).

It answers exactly the requests the governed Confluence Source Sync connector makes
(``services/knowledge/sources/sync/confluence.py`` and ``confluence_acl.py``), with the response
shapes it parses, over ``confluence_fixtures.py``:

- ``GET /rest/api/content?spaceKey=&type=page&status=current&start=&limit=&expand=``: the space
  listing, paged by offset, with version, ancestors and read restrictions;
- ``GET /rest/api/content/{id}?expand=body.view``: the rendered page body;
- ``GET /rest/api/content/{id}/restriction/byOperation/read``: one page's read restrictions;
- ``GET /rest/api/user?username=|key=&expand=details.personal``: one account and the address
  Confluence reports for it (none for a hidden profile; ``accountId`` is Cloud-only: 404);
- ``GET /rest/api/group/{name}/member?start=&limit=``: the members of a group, paged;
- ``GET /rest/api/space/{key}``: the space (for a connection test; the sync does not call it).

Every other request is refused: 405 for any method but GET, 401 without the stub's Basic
credential, 404 for anything unknown. Served by ``server.py confluence`` (``stub_http.py``).

:class:`CloudConfluence` is the Atlassian Cloud-shaped counterpart for tests: everything
under the ``/wiki`` context path, ``_links.base``/``_links.context`` on every collection, a
``_links.webui`` per page, opaque cursor ``_links.next`` (no offsets), version numbers that move on
every edit, accounts known by ``accountId`` only with hidden addresses, CQL change search
(``/rest/api/content/search``) and queued ``429``/``503`` answers with ``Retry-After``. It is
mutable (edit, rename, create, delete, move) so a test can drive freshness end to end. Pages may
have a parent: listings report the ``ancestors`` chain, the page-tree CQL
``space="K" and type=page and (id = N or ancestor = N)`` (optionally ``and lastmodified >= "…"``)
lists a root and its descendants, and ``…/restriction/byOperation/read`` answers a page's own
read restrictions.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, unquote, urlencode

import confluence_fixtures as fixtures
from stub_http import basic_authorization, bounded_int, split_target

MAX_PAGE_SIZE = 200
_USER_QUERY_KEYS = {"username": 0, "key": 1}
_AUTHORIZATION = basic_authorization(fixtures.STUB_USERNAME, fixtures.STUB_TOKEN)


def _user_entry(username: str) -> dict[str, object]:
    user_key, display_name, _ = fixtures.USERS[username]
    return {"type": "known", "username": username, "userKey": user_key, "displayName": display_name}


def _restrictions(page_id: str) -> dict[str, object]:
    page = fixtures.PAGES[page_id]
    users = [_user_entry(name) for name in page["users"]]
    groups = [{"type": "group", "name": name} for name in page["groups"]]
    return {
        "operation": "read",
        "restrictions": {
            "user": {"results": users, "start": 0, "limit": len(users), "size": len(users)},
            "group": {"results": groups, "start": 0, "limit": len(groups), "size": len(groups)},
        },
    }


def _listing_entry(page_id: str) -> dict[str, object]:
    page = fixtures.PAGES[page_id]
    return {
        "id": page_id,
        "type": "page",
        "status": "current",
        "title": page["title"],
        "version": {"number": 1},
        "ancestors": [{"id": ancestor, "type": "page"} for ancestor in page["ancestors"]],
        "restrictions": {"read": _restrictions(page_id)},
        "_links": {"webui": f"/pages/viewpage.action?pageId={page_id}"},
    }


def _paged(results: list, start: int, limit: int, next_path: str) -> dict[str, object]:
    window = results[start : start + limit]
    links: dict[str, str] = {}
    if start + len(window) < len(results):
        links["next"] = f"{next_path}start={start + len(window)}&limit={limit}"
    return {"results": window, "start": start, "limit": limit, "size": len(window), "_links": links}


def _expanded(query: dict[str, list[str]], name: str) -> bool:
    return name in ",".join(query.get("expand") or []).split(",")


def _content_listing(query: dict[str, list[str]]) -> tuple[int, dict]:
    start, limit = bounded_int(query, "start", 0), bounded_int(query, "limit", 25)
    if start is None or limit is None or not 1 <= limit <= MAX_PAGE_SIZE:
        return 400, {"message": "bad paging"}
    space = (query.get("spaceKey") or [""])[0]
    kind = (query.get("type") or ["page"])[0]
    status = (query.get("status") or ["current"])[0]
    pages = list(fixtures.PAGES) if (space, kind, status) == (fixtures.SPACE_KEY, "page", "current") else []
    listing = [_listing_entry(page_id) for page_id in pages]
    return 200, _paged(listing, start, limit, f"/rest/api/content?spaceKey={space}&type=page&status=current&")


def _content(page_id: str, rest: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    if page_id not in fixtures.PAGES:
        return 404, {"message": "no such page"}
    if rest == "/restriction/byOperation/read":
        return 200, _restrictions(page_id)
    if rest:
        return 404, {"message": "unknown content resource"}
    page = fixtures.PAGES[page_id]
    payload: dict[str, object] = {
        "id": page_id,
        "type": "page",
        "status": "current",
        "title": page["title"],
        "version": {"number": 1},
    }
    if _expanded(query, "body.view"):
        payload["body"] = {"view": {"value": page["body"], "representation": "view"}}
    return 200, payload


def _user(query: dict[str, list[str]]) -> tuple[int, dict]:
    found = None
    for parameter, index in _USER_QUERY_KEYS.items():
        wanted = (query.get(parameter) or [None])[0]
        if wanted is not None:
            found = next((name for name, entry in fixtures.USERS.items() if (name, *entry)[index] == wanted), None)
            break
    if found is None:
        return 404, {"message": "no such user"}
    payload: dict[str, object] = _user_entry(found)
    email = fixtures.USERS[found][2]
    if _expanded(query, "details.personal"):
        payload["details"] = {"personal": {"email": email} if email else {}}
    return 200, payload


def _group_members(name: str, query: dict[str, list[str]]) -> tuple[int, dict]:
    if name not in fixtures.GROUPS:
        return 404, {"message": "no such group"}
    members = fixtures.GROUPS[name]
    if members is None:
        return 500, {"message": "member lookup failed"}
    start, limit = bounded_int(query, "start", 0), bounded_int(query, "limit", 50)
    if start is None or limit is None or not 1 <= limit <= MAX_PAGE_SIZE:
        return 400, {"message": "bad paging"}
    entries = [_user_entry(member) for member in members]
    return 200, _paged(entries, start, limit, f"/rest/api/group/{name}/member?")


def handle(method: str, target: str, authorization: str | None) -> tuple[int, dict]:
    """Answer one request: ``(status, JSON body)``. Pure, so tests can call it without a socket."""
    path, query = split_target(target)
    if method != "GET":
        return 405, {"message": "read-only stub"}
    if path == "/healthz":
        return 200, {"status": "ok"}
    if authorization != _AUTHORIZATION:
        return 401, {"message": "unauthorized"}
    if path == "/rest/api/content":
        return _content_listing(query)
    if path.startswith("/rest/api/content/"):
        page_id, _, rest = path.removeprefix("/rest/api/content/").partition("/")
        return _content(page_id, f"/{rest}" if rest else "", query)
    if path == "/rest/api/user":
        return _user(query)
    if path.startswith("/rest/api/group/") and path.endswith("/member"):
        return _group_members(unquote(path.removeprefix("/rest/api/group/").removesuffix("/member")), query)
    if path == f"/rest/api/space/{fixtures.SPACE_KEY}":
        return 200, {"key": fixtures.SPACE_KEY, "name": fixtures.SPACE_NAME, "type": "global"}
    return 404, {"message": "not found"}


class CloudConfluence:
    """An Atlassian Cloud-shaped Confluence space (``/wiki``, cursors, accountId-only users), mutable."""

    CONTEXT = "/wiki"

    def __init__(self, origin: str, *, space: str, principal: str, secret: str) -> None:
        self.origin = origin.rstrip("/")
        self.base = f"{self.origin}{self.CONTEXT}"
        self.space = space
        self._authorization = basic_authorization(principal, secret)
        self.pages: dict[str, dict[str, object]] = {}
        # accountId -> the address Cloud reports (None: hidden by the account's privacy settings).
        self.accounts: dict[str, str | None] = {}
        self.clock = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
        self.throttle: list[tuple[int, str | None]] = []
        # A status the CQL search answers with instead of results (an instance that refuses CQL).
        self.search_status: int | None = None
        self.requests: list[str] = []
        # Page writes (create, update) — off by default: the Knowledge checks need a read-only source.
        self.writable = False

    # --- mutations ------------------------------------------------------------------------------

    def tick(self, minutes: int = 5) -> None:
        self.clock += timedelta(minutes=minutes)

    def put(
        self, page_id: str, title: str, body: str, *, restricted_to_account: str | None = None,
        parent: str | None = None,
    ) -> None:
        self.pages[page_id] = {
            "title": title,
            "body": body,
            "version": 1,
            "modified": self.clock,
            "account": restricted_to_account,
            "parent": parent,
        }

    def move(self, page_id: str, parent: str | None) -> None:
        """Re-parent a page; like Cloud, without a version bump."""
        self.pages[page_id]["parent"] = parent

    def ancestors(self, page_id: str) -> list[str]:
        """The page's ancestors from the top down."""
        chain: list[str] = []
        parent = self.pages[page_id].get("parent")
        while parent is not None and parent in self.pages and parent not in chain:
            chain.insert(0, parent)
            parent = self.pages[parent].get("parent")
        return chain

    def edit(self, page_id: str, *, title: str | None = None, body: str | None = None) -> None:
        page = self.pages[page_id]
        page["title"] = title if title is not None else page["title"]
        page["body"] = body if body is not None else page["body"]
        page["version"] = int(page["version"]) + 1
        page["modified"] = self.clock

    def delete(self, page_id: str) -> None:
        del self.pages[page_id]

    def webui(self, page_id: str) -> str:
        slug = quote(str(self.pages[page_id]["title"]).replace(" ", "+"), safe="+")
        return f"/spaces/{self.space}/pages/{page_id}/{slug}"

    # --- responses ------------------------------------------------------------------------------

    @staticmethod
    def _cursor(offset: int) -> str:
        return "_f_" + base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()

    @staticmethod
    def _offset(cursor: str | None) -> int | None:
        if not cursor:
            return 0
        try:
            return int(json.loads(base64.urlsafe_b64decode(cursor.removeprefix("_f_").encode()))["o"])
        except (ValueError, KeyError, TypeError):
            return None

    def _entry(self, page_id: str) -> dict[str, object]:
        page = self.pages[page_id]
        return {
            "id": page_id,
            "type": "page",
            "status": "current",
            "title": page["title"],
            "version": {"number": page["version"], "when": page["modified"].isoformat()},
            "ancestors": [{"id": ancestor} for ancestor in self.ancestors(page_id)],
            "restrictions": {"read": self._read(page_id)},
            "_links": {"webui": self.webui(page_id), "self": f"{self.base}/rest/api/content/{page_id}"},
        }

    def _full(self, page_id: str) -> dict[str, object]:
        """One page with its body (view and storage), space and links, as ``GET /content/{id}`` answers it."""
        payload = self._entry(page_id)
        body = self.pages[page_id]["body"]
        payload["body"] = {"view": {"value": body, "representation": "view"},
                           "storage": {"value": body, "representation": "storage"}}
        payload["space"] = {"key": self.space}
        payload["_links"] = {**payload["_links"], "base": self.base, "context": self.CONTEXT}
        return payload

    def _read(self, page_id: str) -> dict[str, object]:
        account = self.pages[page_id]["account"]
        users = [{"type": "known", "accountId": account, "accountType": "atlassian"}] if account else []
        return {"operation": "read", "restrictions": {"user": {"results": users}, "group": {"results": []}}}

    def _collection(self, ids: list[str], query: dict[str, list[str]], route: str, extra: dict[str, str]):
        limit = bounded_int(query, "limit", 25)
        offset = self._offset((query.get("cursor") or [None])[0])
        if limit is None or offset is None or not 1 <= limit <= MAX_PAGE_SIZE:
            return 400, {"message": "bad paging"}
        window = ids[offset : offset + limit]
        links: dict[str, str] = {"base": self.base, "context": self.CONTEXT}
        if offset + len(window) < len(ids):
            params = {**extra, "next": "true", "cursor": self._cursor(offset + len(window)), "limit": str(limit)}
            links["next"] = f"{route}?{urlencode(params)}"
        results = [self._entry(page_id) for page_id in window]
        return 200, {"results": results, "limit": limit, "size": len(results), "_links": links}

    def _search(self, query: dict[str, list[str]]):
        cql = (query.get("cql") or [""])[0]
        tree = r"(?: and \(id = (?P<root>\d+) or ancestor = (?P=root)\))?"
        changed = r'(?: and lastmodified >= "(?P<since>[^"]+)")?'
        match = re.fullmatch(rf'space="{re.escape(self.space)}" and type=page{tree}{changed} order by id', cql)
        # The connector asks for a page tree, for changes, or both; never the whole space unfiltered here,
        # and always ordered by id, so offset paging is stable.
        if match is None or (match["root"] is None and match["since"] is None):
            return 400, {"message": "unsupported CQL"}
        root, since_text = match["root"], match["since"]
        try:
            since = datetime.strptime(since_text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC) if since_text else None
        except ValueError:
            return 400, {"message": "bad CQL date"}
        ids = sorted(
            page_id
            for page_id, page in self.pages.items()
            if (since is None or page["modified"] >= since)
            and (root is None or page_id == root or root in self.ancestors(page_id))
        )
        return self._collection(ids, query, "/rest/api/content/search", {"cql": cql})

    def _create(self, body: dict) -> tuple[int, dict]:
        title = str(body.get("title") or "")
        if dict(body.get("space") or {}).get("key") != self.space or not title:
            return 400, {"message": "space and title are required"}
        if any(page["title"] == title for page in self.pages.values()):
            return 400, {"message": "A page with this title already exists"}
        ancestors = body.get("ancestors") or []
        parent = str(ancestors[-1]["id"]) if ancestors else None
        if parent is not None and parent not in self.pages:
            return 400, {"message": "no such parent"}
        page_id = str(max([int(key) for key in self.pages if key.isdigit()] + [1000]) + 1)
        self.put(page_id, title, str(dict(dict(body.get("body") or {}).get("storage") or {}).get("value") or ""),
                 parent=parent)
        return 200, self._entry(page_id)

    def _update(self, page_id: str, body: dict) -> tuple[int, dict]:
        if page_id not in self.pages:
            return 404, {"message": "no such page"}
        expected = int(self.pages[page_id]["version"]) + 1
        if int(dict(body.get("version") or {}).get("number") or 0) != expected:
            return 409, {"message": "version conflict"}
        storage = dict(dict(body.get("body") or {}).get("storage") or {}).get("value")
        self.edit(page_id, title=str(body.get("title") or self.pages[page_id]["title"]),
                  body=str(storage) if storage is not None else None)
        return 200, self._entry(page_id)

    def handle(self, method: str, target: str, authorization: str | None,
               body: dict | None = None) -> tuple[int, dict, dict[str, str]]:
        """``(status, JSON body, headers)`` for one request; pure apart from the recorded request (and, when
        ``writable``, the page a POST creates or a PUT updates)."""
        path, query = split_target(target)
        self.requests.append(f"{method} {path}")
        if method != "GET" and not (self.writable and method in ("POST", "PUT")):
            return 405, {"message": "read-only stub"}, {}
        if not path.startswith(f"{self.CONTEXT}/"):
            return 404, {"message": "Cloud Confluence lives under /wiki"}, {}
        path = path.removeprefix(self.CONTEXT)
        if authorization != self._authorization:
            return 401, {"message": "unauthorized"}, {}
        if self.throttle:
            status, retry_after = self.throttle.pop(0)
            return status, {"message": "throttled"}, ({"Retry-After": retry_after} if retry_after else {})
        if method == "POST" and path == "/rest/api/content":
            status, payload = self._create(body or {})
            return status, payload, {}
        if method == "PUT" and path.startswith("/rest/api/content/"):
            status, payload = self._update(path.removeprefix("/rest/api/content/"), body or {})
            return status, payload, {}
        if path == "/rest/api/content" and (query.get("title") or [""])[0]:
            # A page by title (the write tools' lookup): exactly the page with that title in the space.
            title = (query.get("title") or [""])[0]
            found = [page_id for page_id, page in sorted(self.pages.items()) if page["title"] == title]
            space_ok = (query.get("spaceKey") or [""])[0] == self.space
            results = [self._full(page_id) for page_id in found] if space_ok else []
            return 200, {"results": results[:1], "size": len(results[:1])}, {}
        if path == "/rest/api/content":
            if (query.get("spaceKey") or [""])[0] != self.space:
                return 200, {"results": [], "_links": {"base": self.base, "context": self.CONTEXT}}, {}
            extra = {"spaceKey": self.space, "type": "page", "status": "current"}
            status, payload = self._collection(sorted(self.pages), query, "/rest/api/content", extra)
            return status, payload, {}
        if path == "/rest/api/content/search":
            if self.search_status is not None:
                return self.search_status, {"message": "search refused"}, {}
            status, payload = self._search(query)
            return status, payload, {}
        if path.startswith("/rest/api/content/") and path.endswith("/restriction/byOperation/read"):
            page_id = path.removeprefix("/rest/api/content/").removesuffix("/restriction/byOperation/read")
            if page_id not in self.pages:
                return 404, {"message": "no such page"}, {}
            return 200, self._read(page_id), {}
        if path.startswith("/rest/api/content/"):
            page_id = path.removeprefix("/rest/api/content/")
            if page_id not in self.pages:
                return 404, {"message": "no such page"}, {}
            return 200, self._full(page_id), {}
        if path == "/rest/api/user":
            account = (query.get("accountId") or [None])[0]
            if account not in self.accounts:
                return 404, {"message": "no such user"}, {}
            email = self.accounts[account]
            # Cloud hides the address unless the account's profile makes it visible.
            return 200, {"accountId": account, "accountType": "atlassian", **({"email": email} if email else {})}, {}
        return 404, {"message": "not found"}, {}
