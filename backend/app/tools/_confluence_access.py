"""Internal access policy helpers for Confluence tools."""

from typing import Any

from app.services.atlassian_auth_modes import CONFLUENCE

from ..services.atlassian_auth import auth_headers, request_auth
from ..services.confluence_pages import rules as page_rules
from ..services.outbound_egress import CONNECTION_CONFLUENCE, egress_transport
from .context import ToolContext


def confluence_auth_headers(context: ToolContext) -> dict[str, str]:
    """The ``Authorization`` header of the configured mode; empty when not configured."""
    return auth_headers(CONFLUENCE, context.project_config)


def confluence_client(context: ToolContext, timeout: float) -> dict[str, Any]:
    """The Confluence client options: egress transport, redirects and, for client credentials, the token auth."""
    return {
        "timeout": timeout,
        "follow_redirects": True,
        "transport": egress_transport(CONNECTION_CONFLUENCE),
        "auth": request_auth(CONFLUENCE, context.project_config),
    }


def normalize_space_rules(config: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for entry in config.get("confluence_allowed_spaces") or []:
        if isinstance(entry, str):
            rules.append({"space_key": entry.strip(), "enabled": True})
            continue
        if isinstance(entry, dict):
            space_key = str(entry.get("space_key") or entry.get("key") or "").strip()
            if space_key:
                rules.append(
                    {
                        "space_key": space_key,
                        "enabled": bool(entry.get("enabled", True)),
                        "label": entry.get("label") or space_key,
                    }
                )
    if not rules:
        default_space_key = str(config.get("confluence_space_key") or "").strip()
        if default_space_key:
            rules.append(
                {
                    "space_key": default_space_key,
                    "enabled": True,
                    "label": default_space_key,
                }
            )
    return rules


def normalize_page_rules(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The page allowlist as plain rules (``services/confluence_pages/rules.py`` owns the shape and decision)."""
    return [rule.public() for rule in page_rules.normalize_page_rules(config.get(page_rules.PAGES_FIELD))]


def space_allowed(context: ToolContext, space_key: str) -> bool:
    if not space_key:
        return False
    rules = normalize_space_rules(context.project_config)
    if not rules:
        return False
    for entry in rules:
        if entry["space_key"].lower() == space_key.lower():
            return bool(entry.get("enabled", True))
    return False


def enabled_space_keys(context: ToolContext) -> tuple[str, ...]:
    return tuple(rule["space_key"] for rule in normalize_space_rules(context.project_config) if rule["enabled"])


def page_allowed(
    context: ToolContext,
    *,
    page_id: str | None,
    space_key: str | None,
    ancestor_ids: list[str] | None = None,
) -> bool:
    """The page allowlist decides when it has entries (subtrees with excludes, whole spaces); else the spaces."""
    decision = page_rules.page_decision(
        page_rules.normalize_page_rules(context.project_config.get(page_rules.PAGES_FIELD)),
        page_id=page_id,
        space_key=space_key,
        ancestor_ids=ancestor_ids,
        allowed_spaces=enabled_space_keys(context),
    )
    if decision is not None:
        return decision
    return space_allowed(context, space_key or "")


def complete_ancestor_ids(page: dict[str, Any]) -> list[str] | None:
    """The page's ancestor chain only when **every** entry is a page with an id (root first), else ``None``.

    A location proof (the documentation publisher's direct parent) must never filter: dropping an entry
    without an id would promote the ancestor above it to "direct parent". ``[]`` (a valid empty list) is the space
    root; anything not expanded, not a list, or with one unusable entry is unknown.
    """
    ancestors = page.get("ancestors")
    if not isinstance(ancestors, list):
        return None
    ids = []
    for item in ancestors:
        raw = item.get("id") if isinstance(item, dict) else None
        if type(raw) not in (str, int) or isinstance(raw, bool) or not str(raw).strip().isdigit():
            return None
        ids.append(str(raw).strip())
    return ids


def ancestor_ids_of(page: dict[str, Any]) -> list[str] | None:
    """The ancestor ids of a page payload expanded with ``ancestors`` (root first; ``None`` when not expanded).

    ``[]`` is a top-level page; ``None`` keeps "not fetched" apart from it, so the page allowlist does not
    grant through an entry whose excludes could lie above the page.
    """
    ancestors = page.get("ancestors")
    if not isinstance(ancestors, list):
        return None
    return [str(item.get("id")) for item in ancestors if isinstance(item, dict) and item.get("id")]
