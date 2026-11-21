"""Internal payload builders for Confluence write operations."""

from typing import Any


def build_create_page_payload(
    *,
    space_key: str,
    title: str,
    storage_content: str,
    parent_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": storage_content, "representation": "storage"}},
    }
    if parent_id:
        payload["ancestors"] = [{"id": parent_id}]
    return payload


def build_update_page_payload(
    *,
    title: str,
    version_number: int,
    storage_content: str,
) -> dict[str, Any]:
    return {
        "type": "page",
        "title": title,
        "version": {"number": version_number},
        "body": {"storage": {"value": storage_content, "representation": "storage"}},
    }


def build_add_comment_payload(*, page_id: str, storage_content: str) -> dict[str, Any]:
    return {
        "type": "comment",
        "container": {"id": page_id, "type": "page"},
        "body": {
            "storage": {
                "value": storage_content,
                "representation": "storage",
            }
        },
    }
