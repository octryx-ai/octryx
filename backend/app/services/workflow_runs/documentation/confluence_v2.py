"""A bounded Confluence **Cloud REST v2** page/parent adapter, used only by the publish & prove path."""

from __future__ import annotations

from typing import Any

from .confluence_v2_errors import KIND_NOT_FOUND, SENT_UNKNOWN, V2Error, _malformed
from .confluence_v2_payloads import V2Page, V2Scan, V2Space, _id, parse_child, parse_page, parse_space
from .confluence_v2_transport import V2Transport

TRANSPORT_NAME = "confluence_cloud_v2"
SCAN_PAGE_LIMIT = 250
STATUS_CURRENT = "current"


def _without_fences(title: str, storage: str) -> tuple[str, str]:
    # A page leaves the platform: fence markers from quoted Knowledge or ticket text must not reach Confluence.
    from ...content_security.knowledge_fence import unfence_html, unfence_text

    return unfence_text(title), unfence_html(storage)


async def governed_v2_check(db: Any, run: Any, *, instance: str, connection_id: str, space_key: str,
                           page_id: str | None = None, parent_id: str | None = None,
                           title: str = "", body: str | None = None, base_version: int | None = None) -> Any:
    # This adapter only changes the transport; it waives none of the registry's gates.
    from ....tools._confluence_instance import EXPECTED_CONNECTION_PARAM, EXPECTED_INSTANCE_PARAM
    from ....tools.registry_governance import _run_governed_tool_checks
    from ..platform.dispatch import read_outcome, tool_context

    params: dict[str, Any] = {"space_key": space_key, EXPECTED_INSTANCE_PARAM: instance,
                              EXPECTED_CONNECTION_PARAM: connection_id}
    if body is None:
        tool = "get_confluence_page"
        params["page_id"] = page_id or parent_id or ""
        capability = "read_only"
    elif page_id:
        tool = "update_confluence_page"
        params.update(page_id=page_id, content=body, new_title=title, expected_version=base_version)
        capability = "deliver"
    else:
        tool = "create_confluence_page"
        params.update(title=title, content=body, parent_id=parent_id)
        capability = "deliver"
    context = await tool_context(db, run, capability)
    blocked = await _run_governed_tool_checks(tool, params, context)
    if blocked is None:
        return None
    outcome = read_outcome(blocked)
    if dict(blocked.get("tool_execution") or {}).get("category") == "denied_by_policy":
        from ..platform.dispatch import CLASS_PERMISSION

        outcome.failure_class = CLASS_PERMISSION
    return outcome


class CloudV2Client(V2Transport):

    async def find_space(self, key: str) -> V2Space:
        payload, _ = await self._json("GET", f"{self.base.api}/spaces", params={"keys": key, "limit": 2})
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise _malformed("space results is not a list")
        spaces = [parse_space(item) for item in results]
        # Confluence matches space keys without case (the space "Docs" answers ``keys=DOCS``);
        # the Workspace setting is stored upper case.
        matching = [space for space in spaces if space.key.upper() == key.upper()]
        if len(matching) != 1 or len(spaces) != 1:
            if not spaces:
                raise V2Error(KIND_NOT_FOUND, f"space {key} not found", status_code=None)
            raise _malformed(f"space key {key} did not resolve to exactly one space")
        return matching[0]

    async def get_space(self, space_id: str) -> V2Space:
        payload, _ = await self._json("GET", f"{self.base.api}/spaces/{_id(space_id, 'space id')}")
        return parse_space(payload, expected_id=space_id)

    async def get_page(self, page_id: str, *, version: int | None = None, storage: bool = True) -> V2Page:
        params: dict[str, Any] = {}
        if storage:
            params["body-format"] = "storage"
        if version is not None:
            params["version"] = int(version)
        payload, _ = await self._json("GET", f"{self.base.api}/pages/{_id(page_id, 'page id')}", params=params)
        return parse_page(payload, expected_id=page_id, expected_version=version, want_storage=storage)

    async def scan_direct_children(self, page_id: str) -> V2Scan:
        endpoint = f"{self.base.api}/pages/{_id(page_id, 'page id')}/direct-children"
        return await self._scan(endpoint, {"limit": SCAN_PAGE_LIMIT}, parse_child)

    async def scan_pages_by_title(self, space_id: str, title: str) -> V2Scan:
        endpoint = f"{self.base.api}/pages"
        return await self._scan(endpoint, {"space-id": _id(space_id, "space id"), "title": title,
                                           "status": STATUS_CURRENT, "limit": SCAN_PAGE_LIMIT},
                                lambda item: parse_page(item))

    async def create_page(self, *, space_id: str, parent_id: str, title: str, storage: str) -> V2Page:
        title, storage = _without_fences(title, storage)
        payload, _ = await self._json("POST", f"{self.base.api}/pages", mutating=True, json={
            "spaceId": space_id, "status": STATUS_CURRENT, "title": title, "parentId": parent_id,
            "body": {"representation": "storage", "value": storage}})
        return parse_page(payload, sent=SENT_UNKNOWN)

    async def update_page(self, *, page_id: str, title: str, storage: str, version_number: int,
                          version_message: str) -> V2Page:
        title, storage = _without_fences(title, storage)
        payload, _ = await self._json("PUT", f"{self.base.api}/pages/{_id(page_id, 'page id')}", mutating=True,
                                      json={"id": page_id, "status": STATUS_CURRENT, "title": title,
                                            "body": {"representation": "storage", "value": storage},
                                            "version": {"number": int(version_number),
                                                        "message": version_message}})
        return parse_page(payload, expected_id=page_id, sent=SENT_UNKNOWN)

    async def add_label(self, page_id: str, label: str) -> None:
        await self._send("POST", f"{self.base.site}/rest/api/content/{_id(page_id, 'page id')}/label",
                         json=[{"prefix": "global", "name": label}])  # type: ignore[arg-type]

    def page_link(self, page: V2Page) -> str:
        if page.webui and page.webui.startswith("/") and "//" not in page.webui:
            return f"{self.base.site}{page.webui}"
        return f"{self.base.site}/pages/viewpage.action?pageId={page.id}"


__all__ = ["STATUS_CURRENT", "TRANSPORT_NAME", "CloudV2Client", "governed_v2_check"]
