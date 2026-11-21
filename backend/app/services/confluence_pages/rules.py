"""The Confluence page allowlist (``confluence_allowed_pages``): one decision for the tools and Source Sync.

Stored entries (the shape :func:`validate_page_rules` accepts):

- ``{"id": "<page id>", "title"?, "space_key"?, "enabled": true, "include_children": false}``: this page only;
- the same with ``"include_children": true``: the page and every page below it (its subtree);
- either with ``"enabled": false``: this page itself is excluded (the picker writes it for an excluded page whose
  place in the tree it has not loaded);
- ``{"space_key": "<KEY>", "whole_space": true, "enabled": true}``: every page of that space, for a space that
  stays fully readable while other spaces are narrowed to chosen pages;
- a subtree or whole-space entry may carry ``"excludes": ["<page id>", ...]``: each named page *and everything
  below it* is cut out of what the entry grants ("Page1 and below, but not Page1 → Page3"). A page below an
  exclusion can be granted again by its own entry (its own page, or its own subtree).

Decision for one page (:func:`page_decision`), from its id, title, space and ancestor ids (``None``: not
fetched, unlike ``[]`` for a top-level page):

1. an entry naming the page's id decides: enabled → allowed, disabled → excluded;
2. otherwise an enabled subtree entry among the page's ancestors, or an enabled whole-space entry of the page's
   space (only while that space is an allowed space), grants the page, unless one of the entry's ``excludes``
   is the page or one of its ancestors (an entry with excludes never grants a page whose ancestors are unknown);
3. otherwise, while any page entry exists, the page is not allowed (page entries make the allowlist a page list);
4. without page entries the decision is ``None``: the caller's space allowlist decides.

The ancestor order does not matter: an excluded id below a granting entry is on the page's path exactly when it
is one of the page's ancestors (or the page). Values are validated at save (:func:`validate_page_rules`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PAGES_FIELD = "confluence_allowed_pages"
MAX_PAGE_RULES = 500
MAX_EXCLUDES = 200
PAGE_ID = re.compile(r"^[0-9]{1,20}$")
SPACE_KEY = re.compile(r"^~?[A-Za-z0-9_]{1,64}$")


@dataclass(frozen=True, slots=True)
class PageRule:
    page_id: str
    title: str
    space_key: str
    enabled: bool
    include_children: bool
    whole_space: bool
    excludes: frozenset[str]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.page_id, "title": self.title, "space_key": self.space_key, "enabled": self.enabled,
            "include_children": self.include_children, "whole_space": self.whole_space,
            "excludes": sorted(self.excludes),
        }


def _text(value: object) -> str:
    return str(value or "").strip()


def _excludes(raw: object) -> frozenset[str]:
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(_text(item) for item in raw if _text(item))


def normalize_page_rules(raw: object) -> tuple[PageRule, ...]:
    """The stored entries as rules: a page entry names a page id, a whole-space entry a space key."""
    rules: list[PageRule] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        page_id, space_key = _text(entry.get("id")), _text(entry.get("space_key"))
        whole_space = entry.get("whole_space") is True and bool(space_key) and not page_id
        if not (page_id or whole_space):
            continue
        rules.append(
            PageRule(
                page_id=page_id,
                title=_text(entry.get("title")),
                space_key=space_key,
                enabled=entry.get("enabled") is not False,
                include_children=entry.get("include_children") is True and not whole_space,
                whole_space=whole_space,
                excludes=_excludes(entry.get("excludes")),
            )
        )
    return tuple(rules)


def _own_rule(rules: Iterable[PageRule], page_id: str) -> PageRule | None:
    if not page_id:
        return None
    return next((rule for rule in rules if not rule.whole_space and rule.page_id == page_id), None)


def page_decision(
    rules: tuple[PageRule, ...],
    *,
    page_id: str | None,
    space_key: str | None,
    ancestor_ids: Iterable[str] | None = None,
    allowed_spaces: Iterable[str] = (),
) -> bool | None:
    """Whether the page is allowed by the page rules; ``None`` without page rules (the spaces decide)."""
    if not rules:
        return None
    page = _text(page_id)
    own = _own_rule(rules, page)
    if own is not None:
        return own.enabled
    # ``None``: the ancestors were not fetched (unknown); ``[]``: a top-level page.
    ancestors_known = ancestor_ids is not None
    ancestors = {_text(item) for item in ancestor_ids or () if _text(item)}
    path = ancestors | ({page} if page else set())
    space = _text(space_key).upper()
    spaces = {_text(item).upper() for item in allowed_spaces}
    for rule in rules:
        if not rule.enabled:
            continue
        grants = (rule.include_children and rule.page_id in ancestors) or (
            rule.whole_space and space and rule.space_key.upper() == space and space in spaces
        )
        # Without the ancestors an exclude above the page cannot be ruled out: such an entry does not grant.
        if grants and not rule.excludes & path and (ancestors_known or not rule.excludes):
            return True
    return False


def whole_space_keys(rules: tuple[PageRule, ...]) -> tuple[str, ...]:
    return tuple(rule.space_key for rule in rules if rule.whole_space and rule.enabled)


def validate_page_rules(value: Any) -> None:
    """Refuse a page allowlist the decision cannot read unambiguously (``ValueError`` naming the problem)."""
    if not isinstance(value, list):
        raise ValueError(f"{PAGES_FIELD} must be a list")
    if len(value) > MAX_PAGE_RULES:
        raise ValueError(f"{PAGES_FIELD} holds at most {MAX_PAGE_RULES} entries")
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{PAGES_FIELD} must contain objects")
        whole_space = item.get("whole_space")
        if whole_space not in (None, False, True):
            raise ValueError(f"{PAGES_FIELD}: whole_space must be true or false")
        if whole_space is True:
            if item.get("enabled") is False:
                raise ValueError(f"{PAGES_FIELD}: a whole_space entry cannot be disabled; remove it instead")
            if _text(item.get("id")):
                raise ValueError(f"{PAGES_FIELD}: a whole_space entry names a space, not a page id")
            if not SPACE_KEY.fullmatch(_text(item.get("space_key"))):
                raise ValueError(f"{PAGES_FIELD}: a whole_space entry needs a valid space_key")
        elif not _text(item.get("id")):
            raise ValueError(f"{PAGES_FIELD} entries must include id")
        excludes = item.get("excludes")
        if excludes is None:
            continue
        if not (whole_space is True or item.get("include_children") is True):
            raise ValueError(f"{PAGES_FIELD}: excludes belong to a subtree or whole_space entry")
        if not isinstance(excludes, list) or len(excludes) > MAX_EXCLUDES:
            raise ValueError(f"{PAGES_FIELD}: excludes must be a list of at most {MAX_EXCLUDES} page ids")
        if not all(isinstance(page, str) and PAGE_ID.fullmatch(page) for page in excludes):
            raise ValueError(f"{PAGES_FIELD}: excludes must be page ids (digits)")


__all__ = [
    "MAX_EXCLUDES",
    "MAX_PAGE_RULES",
    "PAGES_FIELD",
    "PageRule",
    "normalize_page_rules",
    "page_decision",
    "validate_page_rules",
    "whole_space_keys",
]
