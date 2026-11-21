"""The page-tree part of a Confluence connector's scope.

Besides whole spaces (``spaces``), a Confluence connector may name page trees:
``"page_trees": [{"space_key": "DEMO", "root_page_id": "100002"}]``, each the root page and all of
its descendants. Values are refused, never cleaned up: a space key exactly as Confluence writes it,
a root page id as a string of digits (a pasted page URL is the UI's to turn into an id, visibly), no
duplicate tree, and no tree inside a space the connector already lists whole (its pages would be
listed twice). Every refusal is an :class:`InvalidPageTreeError` with a fixed code (422).

The tree's space must lie inside the Workspace's ``confluence_allowed_spaces`` like any listed
space (``config.scope_within_connection``). The listing asks CQL for
``space = "<key>" and type = page and (id = <root> or ancestor = <root>)``, so a root outside its
declared space lists nothing, and a page moved out of the tree is retired when the pass completes.
"""

from __future__ import annotations

import re

SPACE_KEY = re.compile(r"^~?[A-Za-z0-9_]{1,64}$")
ROOT_PAGE_ID = re.compile(r"^[0-9]{1,20}$")
MAX_PAGE_TREES = 20
FIELD = "page_trees"
_TREE_KEYS = frozenset({"space_key", "root_page_id"})

CODE_INVALID = "page_trees_invalid"
CODE_SPACE_INVALID = "page_tree_space_invalid"
CODE_ROOT_INVALID = "page_tree_root_invalid"
CODE_DUPLICATE = "page_tree_duplicate"
CODE_IN_LISTED_SPACE = "page_tree_in_listed_space"
CODE_CONFLUENCE_ONLY = "page_trees_confluence_only"


class InvalidPageTreeError(ValueError):
    """A refused page-tree scope; ``code`` and ``field`` are fixed strings, never a value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.field = FIELD


def validate_page_trees(raw: object, *, spaces: tuple[str, ...]) -> list[dict[str, str]]:
    """The validated trees (``[]`` for none); ``spaces`` are the spaces the connector lists whole."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_PAGE_TREES:
        raise InvalidPageTreeError(CODE_INVALID)
    trees: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != _TREE_KEYS:
            raise InvalidPageTreeError(CODE_INVALID)
        space_key, root = entry["space_key"], entry["root_page_id"]
        if type(space_key) is not str or not SPACE_KEY.fullmatch(space_key):
            raise InvalidPageTreeError(CODE_SPACE_INVALID)
        if type(root) is not str or not ROOT_PAGE_ID.fullmatch(root):
            raise InvalidPageTreeError(CODE_ROOT_INVALID)
        if any(tree["root_page_id"] == root for tree in trees):
            raise InvalidPageTreeError(CODE_DUPLICATE)
        if space_key.upper() in {space.upper() for space in spaces}:
            raise InvalidPageTreeError(CODE_IN_LISTED_SPACE)
        trees.append({"space_key": space_key, "root_page_id": root})
    return trees


def tree_cql(tree: dict[str, str]) -> str:
    """The CQL of one page tree; keys and ids are validated, so nothing here needs quoting rules."""
    root = tree["root_page_id"]
    return f'space="{tree["space_key"]}" and type=page and (id = {root} or ancestor = {root})'


def scope_space_keys(scope: dict) -> tuple[str, ...]:
    """Every space a Confluence scope reads: the whole spaces and the spaces of its page trees."""
    trees = scope.get("page_trees") or ()
    return (*(scope.get("spaces") or ()), *(str(tree.get("space_key") or "") for tree in trees))


__all__ = [
    "CODE_CONFLUENCE_ONLY",
    "CODE_DUPLICATE",
    "CODE_INVALID",
    "CODE_IN_LISTED_SPACE",
    "CODE_ROOT_INVALID",
    "CODE_SPACE_INVALID",
    "InvalidPageTreeError",
    "SPACE_KEY",
    "scope_space_keys",
    "tree_cql",
    "validate_page_trees",
]
