"""Storage body digests of the publish & prove path: exact bytes, and provider serialization equivalence."""

from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from typing import Any


def storage_digest(storage: str | None) -> str:
    """``sha256:<hex>`` of a storage body exactly as given."""
    return "sha256:" + hashlib.sha256(str(storage or "").encode("utf-8")).hexdigest()


class _StorageTokens(HTMLParser):
    """Compare storage structure while preserving every text byte, including pre/code whitespace."""

    VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "wbr", "area", "base", "embed", "param",
                      "source", "track", "col"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tokens.append(("start", tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID:
            self.tokens.append(("end", tag))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self.tokens.append(("text", data))

    def handle_comment(self, data: str) -> None:
        self.tokens.append(("comment", data))

    def handle_decl(self, decl: str) -> None:
        self.tokens.append(("declaration", decl))


def canonical_storage(storage: str | None) -> str:
    """Provider serialization equivalence, never general whitespace normalization.

    Only parsed entity spelling and void-tag slash/spacing differ. Text and attribute
    values remain exact; escaped markup is a text token rather than a tag token.
    """
    parser = _StorageTokens()
    parser.feed(str(storage or ""))
    parser.close()
    return json.dumps(parser.tokens, ensure_ascii=False, separators=(",", ":"))


def canonical_digest(storage: str | None) -> str:
    return storage_digest(canonical_storage(storage))
