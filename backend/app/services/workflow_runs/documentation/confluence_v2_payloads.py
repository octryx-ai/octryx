"""Strict validation of Confluence Cloud v2 answers (``confluence_v2``): spaces, pages, children and scans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .confluence_v2_errors import SENT_NO, V2Error, _malformed

_PAGE_STATUSES = frozenset({"current", "draft", "archived", "historical", "trashed", "deleted"})


@dataclass(frozen=True, slots=True)
class V2Space:
    id: str
    key: str


@dataclass(frozen=True, slots=True)
class V2Page:
    id: str
    status: str
    title: str
    space_id: str
    parent_id: str | None
    version: int
    version_message: str | None = None
    storage: str | None = None
    webui: str | None = None


@dataclass(frozen=True, slots=True)
class V2Child:
    id: str
    type: str
    status: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class V2Scan:
    items: tuple[Any, ...]
    complete: bool
    reason: str = ""
    pages_read: int = 0


def _id(value: Any, what: str) -> str:
    if isinstance(value, bool) or type(value) not in (str, int):
        raise _malformed(f"{what} is not an id")
    text = str(value).strip()
    if not text.isdigit():
        raise _malformed(f"{what} is not a numeric id")
    return text


def _optional_id(value: Any, what: str) -> str | None:
    return None if value is None else _id(value, what)


def _text(value: Any, what: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise _malformed(f"{what} is missing")
    return value


def parse_space(payload: Any, *, expected_id: str | None = None) -> V2Space:
    if not isinstance(payload, dict):
        raise _malformed("space is not an object")
    space = V2Space(id=_id(payload.get("id"), "space id"), key=str(_text(payload.get("key"), "space key")))
    if expected_id is not None and space.id != expected_id:
        raise _malformed(f"space {space.id} answered for {expected_id}")
    return space


def parse_page(payload: Any, *, expected_id: str | None = None, expected_version: int | None = None,
               want_storage: bool = False, sent: str = SENT_NO) -> V2Page:
    try:
        if not isinstance(payload, dict):
            raise _malformed("page is not an object")
        page_id = _id(payload.get("id"), "page id")
        if expected_id is not None and page_id != expected_id:
            raise _malformed(f"page {page_id} answered for {expected_id}")
        status = str(_text(payload.get("status"), "page status"))
        if status not in _PAGE_STATUSES:
            raise _malformed(f"page status {status!r} is unknown")
        version = payload.get("version")
        number = version.get("number") if isinstance(version, dict) else None
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise _malformed("page version is not a positive number")
        if expected_version is not None and number != expected_version:
            raise _malformed(f"page version {number} answered for version {expected_version}")
        message = version.get("message") if isinstance(version, dict) else None
        storage = None
        body = payload.get("body")
        if want_storage:
            node = body.get("storage") if isinstance(body, dict) else None
            if not isinstance(node, dict) or not isinstance(node.get("value"), str):
                raise _malformed("page storage body is missing")
            if node.get("representation") not in (None, "storage"):
                raise _malformed("page body is not the storage representation")
            storage = node["value"]
        elif isinstance(body, dict) and isinstance(body.get("storage"), dict) and isinstance(
                body["storage"].get("value"), str):
            storage = body["storage"]["value"]
        links = payload.get("_links")
        webui = links.get("webui") if isinstance(links, dict) and isinstance(links.get("webui"), str) else None
        return V2Page(id=page_id, status=status, title=str(_text(payload.get("title"), "page title")),
                      space_id=_id(payload.get("spaceId"), "page spaceId"),
                      parent_id=_optional_id(payload.get("parentId"), "page parentId"), version=number,
                      version_message=message if isinstance(message, str) else None, storage=storage, webui=webui)
    except V2Error as error:
        raise V2Error(error.kind, str(error), sent=sent) from None


def parse_child(payload: Any) -> V2Child:
    if not isinstance(payload, dict):
        raise _malformed("child entry is not an object")
    status = payload.get("status")
    title = payload.get("title")
    return V2Child(id=_id(payload.get("id"), "child id"), type=str(_text(payload.get("type"), "child type")),
                   status=status if isinstance(status, str) else None, title=title if isinstance(title, str) else None)
