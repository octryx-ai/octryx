"""The data-flow rules of the documentation steps (``data_flow``): who produces what the publication needs.

The publish & prove steps (``s1_graph.py``) form one chain, so a definition that drops a step is refused at
publish instead of failing closed at run time:

- a ``publication`` confirmation (card (b)) produces ``confirmed_documentation``;
- ``documentation.publish_v2`` consumes ``confirmed_documentation`` and produces ``documentation_page``;
- ``documentation.sync_published_version`` consumes ``documentation_page``.
"""

from __future__ import annotations

from typing import Any

CONFIRMED_DOCUMENTATION = "confirmed_documentation"
DOCUMENTATION_PAGE = "documentation_page"
PUBLICATION_SUBJECT = "publication"
PUBLISH_V2 = "documentation.publish_v2"
SYNC_PUBLISHED_VERSION = "documentation.sync_published_version"


def _text(value: Any) -> str:
    return str(value or "").strip()


def documentation_produces(kind: str, config: dict[str, Any]) -> set[str]:
    if kind == "user_confirmation" and _text(config.get("subject")) == PUBLICATION_SUBJECT:
        return {CONFIRMED_DOCUMENTATION}
    action = _text(config.get("action")) if kind == "platform_action" else ""
    if action == PUBLISH_V2:
        return {DOCUMENTATION_PAGE}
    return set()


def documentation_consumes(kind: str, config: dict[str, Any]) -> set[str]:
    action = _text(config.get("action")) if kind == "platform_action" else ""
    if action == PUBLISH_V2:
        return {CONFIRMED_DOCUMENTATION}
    if action == SYNC_PUBLISHED_VERSION:
        return {DOCUMENTATION_PAGE}
    return set()
